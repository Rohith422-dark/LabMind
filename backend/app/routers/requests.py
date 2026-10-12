import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import require
from app.models.tables import InventoryTransaction, Reagent, ReagentRequest, User
from app.services import audit, inventory as inv
from app.services.notify import notify

router = APIRouter(prefix="/requests", tags=["requests"])


class RequestIn(BaseModel):
    reagent_id: uuid.UUID
    quantity: float = Field(gt=0)
    purpose: str | None = Field(default=None, max_length=1000)
    experiment_ref: str | None = Field(default=None, max_length=120)


class RequestOut(BaseModel):
    id: uuid.UUID
    reagent_id: uuid.UUID
    reagent_name: str
    unit: str | None = None
    quantity: float
    purpose: str | None = None
    experiment_ref: str | None = None
    status: str
    reject_reason: str | None = None
    requested_by: uuid.UUID
    requester_name: str | None = None
    issued_lot_id: uuid.UUID | None = None
    created_at: datetime
    handled_at: datetime | None = None


class IssueIn(BaseModel):
    lot_id: uuid.UUID


class RejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


SELECT = """
SELECT q.id, q.reagent_id, r.name AS reagent_name, r.unit, q.quantity, q.purpose, q.experiment_ref, q.status,
       q.reject_reason, q.requested_by, u.full_name AS requester_name, q.issued_lot_id, q.created_at, q.handled_at
FROM reagent_requests q JOIN reagents r ON r.id = q.reagent_id JOIN users u ON u.id = q.requested_by
"""


def _out(r) -> RequestOut:
    d = dict(r)
    d["quantity"] = float(d["quantity"])
    return RequestOut(**d)


@router.post("", response_model=RequestOut, status_code=201)
async def create_request(request: Request, body: RequestIn, user: User = require("requests.create"),
                         session: AsyncSession = Depends(get_session)):
    if await session.get(Reagent, body.reagent_id) is None:
        raise HTTPException(404, "Reagent not found")
    req = ReagentRequest(requested_by=user.id, reagent_id=body.reagent_id, quantity=body.quantity,
                         purpose=body.purpose, experiment_ref=body.experiment_ref, status="pending")
    session.add(req)
    await session.flush()
    for a in (await session.execute(select(User).where(User.role == "lab_analyst"))).scalars():
        await notify(session, a.id, f"New reagent request from {user.full_name}", "/analyst")
    await audit.log(session, user, "reagent_requested", str(body.reagent_id),
                    {"request_id": str(req.id), "quantity": body.quantity}, audit.client_ip(request))
    await session.commit()
    row = (await session.execute(text(SELECT + " WHERE q.id = :id"), {"id": req.id})).mappings().first()
    return _out(row)


@router.get("/mine", response_model=list[RequestOut])
async def my_requests(user: User = require("requests.create"), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(text(SELECT + " WHERE q.requested_by = :u ORDER BY q.created_at DESC"),
                                  {"u": user.id})).mappings().all()
    return [_out(r) for r in rows]


@router.get("/pending", response_model=list[RequestOut])
async def pending(user: User = require("inventory.manage"), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(text(SELECT + " WHERE q.status = 'pending' ORDER BY q.created_at"))).mappings().all()
    return [_out(r) for r in rows]


async def _get_pending_locked(session: AsyncSession, request_id: uuid.UUID) -> ReagentRequest:
    req = (await session.execute(select(ReagentRequest).where(ReagentRequest.id == request_id)
                                 .with_for_update())).scalar_one_or_none()
    if req is None:
        raise HTTPException(404, "Request not found")
    if req.status != "pending":
        raise HTTPException(409, f"This request was already {req.status}.")
    return req


@router.post("/{request_id}/issue", response_model=RequestOut)
async def issue(request: Request, request_id: uuid.UUID, body: IssueIn, user: User = require("inventory.manage"),
                session: AsyncSession = Depends(get_session)):
    req = await _get_pending_locked(session, request_id)
    reagent_id, qty = req.reagent_id, float(req.quantity)  # plain values survive a rollback
    # ONE atomic statement: stock check + expiry check + decrement. Zero rows -> nothing written.
    res = await session.execute(text(
        "UPDATE reagent_lots SET quantity_available = quantity_available - :q "
        "WHERE id = :lot AND reagent_id = :rid AND quantity_available >= :q "
        "AND (expiry_date IS NULL OR expiry_date > current_date) RETURNING id, lot_no, quantity_available"),
        {"q": qty, "lot": body.lot_id, "rid": reagent_id})
    row = res.first()
    if row is None:
        await session.rollback()
        lot = (await session.execute(text("SELECT reagent_id, quantity_available, expiry_date FROM reagent_lots WHERE id=:i"),
                                     {"i": body.lot_id})).first()
        if lot is None or lot.reagent_id != reagent_id:
            raise HTTPException(409, "That lot does not match the requested reagent.")
        if lot.expiry_date is not None and lot.expiry_date <= date.today():
            raise HTTPException(409, "That lot is expired and cannot be issued.")
        raise HTTPException(409, "Not enough stock in that lot.")
    session.add(InventoryTransaction(lot_id=body.lot_id, type="issued", quantity=req.quantity, performed_by=user.id,
                                     issued_to=req.requested_by, reason=f"request {req.id}"))
    req.status, req.handled_by, req.issued_lot_id = "issued", user.id, body.lot_id
    req.handled_at = datetime.now(timezone.utc)
    await notify(session, req.requested_by, f"Your reagent request was issued (lot {row.lot_no}).", "/my-requests")
    await audit.log(session, user, "reagent_issued", row.lot_no,
                    {"request_id": str(req.id), "quantity": float(req.quantity), "remaining": float(row.quantity_available)},
                    audit.client_ip(request))
    await session.commit()
    out = (await session.execute(text(SELECT + " WHERE q.id = :id"), {"id": request_id})).mappings().first()
    return _out(out)


@router.post("/{request_id}/reject", response_model=RequestOut)
async def reject(request: Request, request_id: uuid.UUID, body: RejectIn, user: User = require("inventory.manage"),
                 session: AsyncSession = Depends(get_session)):
    req = await _get_pending_locked(session, request_id)
    req.status, req.handled_by, req.reject_reason = "rejected", user.id, body.reason
    req.handled_at = datetime.now(timezone.utc)
    await notify(session, req.requested_by, f"Your reagent request was rejected: {body.reason}", "/my-requests")
    await audit.log(session, user, "request_rejected", str(req.id), {"reason": body.reason}, audit.client_ip(request))
    await session.commit()
    out = (await session.execute(text(SELECT + " WHERE q.id = :id"), {"id": request_id})).mappings().first()
    return _out(out)
