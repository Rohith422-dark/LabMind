"""Reagent requests: any signed-in user submits and tracks their own; lab assistants (inventory.manage) review and fulfil.

Object-level rules (on top of the role checks): a requester can only ever read or answer THEIR OWN request - every other
id is a 404 - and only holders of `inventory.manage` can move a request through the lifecycle or touch stock.
"""
import math
import uuid
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import require
from app.limiter import limiter
from app.models.tables import InventoryTransaction, Reagent, ReagentRequest, User
from app.services import audit, inventory as inv, request_workflow as wf
from app.services.access import role_of
from app.services.notify import notify

router = APIRouter(prefix="/requests", tags=["requests"])
MAX_QTY = 1e7


class RequestIn(BaseModel):
    reagent_id: uuid.UUID | None = None
    reagent_name: str | None = Field(default=None, max_length=200)     # reagent not yet in the register
    quantity: float = Field(gt=0, le=MAX_QTY)
    unit: str | None = Field(default=None, max_length=16)
    reason: str = Field(min_length=3, max_length=1000, validation_alias=AliasChoices("reason", "purpose"))
    details: str | None = Field(default=None, max_length=4000)
    urgency: str = Field(default="normal", pattern="^(low|normal|high|urgent)$")
    project_id: uuid.UUID | None = None
    experiment_ref: str | None = Field(default=None, max_length=120)

    @field_validator("quantity")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("quantity must be a finite number")
        return v

    @model_validator(mode="after")
    def _reagent(self):
        if not self.reagent_id and not (self.reagent_name or "").strip():
            raise ValueError("choose a reagent from the register or enter the name of the missing reagent")
        return self


class RequestOut(BaseModel):
    id: uuid.UUID
    reagent_id: uuid.UUID | None = None
    reagent_name: str
    in_register: bool = True
    unit: str | None = None
    quantity: float
    purpose: str | None = None           # the stated reason (kept under its original name for existing clients)
    details: str | None = None
    urgency: str = "normal"
    experiment_ref: str | None = None
    project_id: uuid.UUID | None = None
    project_name: str | None = None
    status: str
    reject_reason: str | None = None
    requested_by: uuid.UUID
    requester_name: str | None = None
    handler_name: str | None = None
    issued_lot_id: uuid.UUID | None = None
    reserved_lot_id: uuid.UUID | None = None
    reserved_quantity: float = 0
    fulfilment_note: str | None = None
    reagent_availability: str | None = None        # current register status of the reagent (e.g. restocked meanwhile)
    reagent_availability_label: str | None = None
    created_at: datetime
    handled_at: datetime | None = None
    fulfilled_at: datetime | None = None


class EventOut(BaseModel):
    id: int
    kind: str
    from_status: str | None = None
    to_status: str | None = None
    actor_id: uuid.UUID
    actor_name: str | None = None
    actor_role: str | None = None
    comment: str | None = None
    created_at: datetime


class RequestDetail(RequestOut):
    events: list[EventOut]
    allowed_next: list[str] = []


class RequestPage(BaseModel):
    items: list[RequestOut]
    total: int
    limit: int
    offset: int


class TransitionIn(BaseModel):
    to_status: str
    comment: str | None = Field(default=None, max_length=2000)
    reserve_lot_id: uuid.UUID | None = None            # only with to_status = approved: hold stock from this lot
    reserve_quantity: float | None = Field(default=None, gt=0, le=MAX_QTY)


class FulfilIn(BaseModel):
    note: str = Field(min_length=3, max_length=2000)
    lot_id: uuid.UUID | None = None
    issue_from_lot: bool = False                       # True: decrease this lot's stock by the requested quantity now


class RespondIn(BaseModel):
    comment: str = Field(min_length=1, max_length=2000)


class CommentIn(BaseModel):
    comment: str = Field(min_length=1, max_length=2000)


class IssueIn(BaseModel):                              # legacy one-click path (approve + fulfil from a lot)
    lot_id: uuid.UUID


class RejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


SELECT = """
SELECT q.id, q.reagent_id, COALESCE(r.name, q.reagent_name_text) AS reagent_name, (q.reagent_id IS NOT NULL) AS in_register,
       COALESCE(q.unit, r.unit) AS unit, q.quantity, q.purpose, q.details, q.urgency, q.experiment_ref, q.project_id,
       pr.name AS project_name, q.status, q.reject_reason, q.requested_by, u.full_name AS requester_name,
       h.full_name AS handler_name, q.issued_lot_id, q.reserved_lot_id, q.reserved_quantity, q.fulfilment_note,
       q.created_at, q.handled_at, q.fulfilled_at
FROM reagent_requests q
LEFT JOIN reagents r ON r.id = q.reagent_id JOIN users u ON u.id = q.requested_by
LEFT JOIN users h ON h.id = q.handled_by LEFT JOIN projects pr ON pr.id = q.project_id
"""


async def _outs(session: AsyncSession, rows) -> list[RequestOut]:
    avail = {s["reagent_id"]: s for s in await inv.reagent_summaries(session)} if rows else {}
    out = []
    for r in rows:
        d = dict(r)
        d["quantity"], d["reserved_quantity"] = float(d["quantity"]), float(d["reserved_quantity"] or 0)
        a = avail.get(d["reagent_id"])
        out.append(RequestOut(**d, reagent_availability=a and a["status"], reagent_availability_label=a and a["status_label"]))
    return out


async def _one(session: AsyncSession, request_id: uuid.UUID) -> RequestOut:
    row = (await session.execute(text(SELECT + " WHERE q.id = :id"), {"id": request_id})).mappings().first()
    return (await _outs(session, [row]))[0]


async def _events(session: AsyncSession, request_id: uuid.UUID) -> list[EventOut]:
    rows = (await session.execute(text(
        "SELECT e.id, e.kind, e.from_status, e.to_status, e.actor_id, u.full_name AS actor_name, u.role AS actor_role, e.comment, e.created_at "
        "FROM request_events e JOIN users u ON u.id = e.actor_id WHERE e.request_id = :r ORDER BY e.id"), {"r": request_id})).mappings().all()
    return [EventOut(**dict(r)) for r in rows]


async def _locked(session: AsyncSession, request_id: uuid.UUID) -> ReagentRequest:
    req = (await session.execute(select(ReagentRequest).where(ReagentRequest.id == request_id).with_for_update())).scalar_one_or_none()
    if req is None:
        raise HTTPException(404, "Request not found")
    return req


def _qty_in(req: ReagentRequest, unit: str | None) -> float:
    """Requested quantity expressed in `unit` (the reagent's register unit). 409 if the units cannot be reconciled."""
    q = float(req.quantity)
    ru, tu = wf.normalize_unit(req.unit), wf.normalize_unit(unit)
    if not ru or not tu or ru == tu:
        return q
    c = wf.convert(q, ru, tu)
    if c is None:
        raise HTTPException(409, f"The request is in {req.unit} but the register tracks this reagent in {unit}; these cannot be converted.")
    return c


async def _release_reservation(session: AsyncSession, req: ReagentRequest) -> None:
    if req.reserved_lot_id and float(req.reserved_quantity or 0) > 0:
        await session.execute(text(
            "UPDATE reagent_lots SET reserved_quantity = GREATEST(reserved_quantity - :q, 0), row_version = row_version + 1 WHERE id = :l"),
            {"q": float(req.reserved_quantity), "l": req.reserved_lot_id})
    req.reserved_lot_id, req.reserved_quantity = None, 0


async def _status_change(session: AsyncSession, req: ReagentRequest, actor: User, to: str, comment: str | None, ip: str | None,
                         notice: str | None = None) -> None:
    try:
        wf.check_transition(req.status, to)
    except wf.InvalidTransition as e:
        raise HTTPException(409, str(e))
    prev = req.status
    req.status = to
    if actor.role == "lab_analyst":
        req.handled_by, req.handled_at = actor.id, datetime.now(timezone.utc)
    await wf.add_event(session, req.id, actor, "status", prev, to, comment)
    if notice and actor.id != req.requested_by:
        await notify(session, req.requested_by, notice, "/my-requests", kind=f"request_{to}")
    await audit.log(session, actor, f"request_{to}", str(req.id), {"from": prev, "comment": (comment or "")[:200]}, ip)


# ------------------------------------------------------------------ requester
@router.post("", response_model=RequestOut, status_code=201)
@limiter.limit("60/minute")
async def create_request(request: Request, body: RequestIn, user: User = require("requests.create"),
                         session: AsyncSession = Depends(get_session)):
    reagent: Reagent | None = None
    if body.reagent_id:
        reagent = await session.get(Reagent, body.reagent_id)
        if reagent is None:
            raise HTTPException(404, "Reagent not found")
    unit = wf.normalize_unit(body.unit) if body.unit else None
    if body.unit and unit is None:
        raise HTTPException(422, f"Unknown unit '{body.unit}'. Use one of: {', '.join(wf.UNIT_CHOICES)}")
    if reagent is not None:
        reg_unit = wf.normalize_unit(reagent.unit)
        unit = unit or reg_unit or None
        if unit and reg_unit and wf.family(unit) != wf.family(reg_unit):
            raise HTTPException(422, f"'{unit}' is not compatible with this reagent's unit ({reagent.unit}).")
    elif unit is None:
        raise HTTPException(422, "A unit is required when requesting a reagent that is not in the register")
    if body.project_id and await role_of(session, user.id, body.project_id) is None:
        raise HTTPException(422, "Project not found")      # same answer whether it exists or not
    req = ReagentRequest(requested_by=user.id, reagent_id=body.reagent_id,
                         reagent_name_text=None if reagent else (body.reagent_name or "").strip(), quantity=body.quantity, unit=unit,
                         purpose=body.reason.strip(), details=body.details, urgency=body.urgency, project_id=body.project_id,
                         experiment_ref=body.experiment_ref, status="submitted")
    session.add(req)
    await session.flush()
    await wf.add_event(session, req.id, user, "status", None, "submitted", None)
    name = reagent.name if reagent else req.reagent_name_text
    await wf.notify_assistants(session, f"New reagent request from {user.full_name}: {body.quantity:g} {unit or ''} {name}"
                               + (" (URGENT)" if body.urgency == "urgent" else ""), "/analyst", "request_submitted", exclude=user.id)
    await audit.log(session, user, "reagent_requested", name, {"request_id": str(req.id), "quantity": body.quantity, "unit": unit,
                                                               "urgency": body.urgency}, audit.client_ip(request))
    await session.commit()
    return await _one(session, req.id)


@router.get("/mine", response_model=list[RequestOut])
async def my_requests(status: str | None = None, limit: int = Query(100, ge=1, le=200), user: User = require("requests.create"),
                      session: AsyncSession = Depends(get_session)):
    sql = SELECT + " WHERE q.requested_by = :u" + (" AND q.status = :s" if status else "") + " ORDER BY q.created_at DESC LIMIT :n"
    rows = (await session.execute(text(sql), {"u": user.id, "n": limit, **({"s": status} if status else {})})).mappings().all()
    return await _outs(session, rows)


@router.get("/pending", response_model=list[RequestOut])
async def pending(user: User = require("inventory.manage"), session: AsyncSession = Depends(get_session)):
    """Everything still open (not rejected/fulfilled), oldest first."""
    rows = (await session.execute(text(SELECT + " WHERE q.status = ANY(:o) ORDER BY q.created_at"),
                                  {"o": list(wf.OPEN_STATUSES)})).mappings().all()
    return await _outs(session, rows)


@router.get("", response_model=RequestPage)
async def manage_list(status: str | None = None, reagent: str | None = Query(None, max_length=200),
                      requester: str | None = Query(None, max_length=120),
                      urgency: str | None = Query(None, pattern="^(low|normal|high|urgent)$"),
                      date_from: date | None = None, date_to: date | None = None, limit: int = Query(25, ge=1, le=100),
                      offset: int = Query(0, ge=0), user: User = require("inventory.manage"),
                      session: AsyncSession = Depends(get_session)):
    where, p = ["true"], {"lim": limit, "off": offset}
    if status:
        where.append("q.status = :status")
        p["status"] = status
    if reagent:
        where.append("COALESCE(r.name, q.reagent_name_text) ILIKE :reagent")
        p["reagent"] = f"%{reagent}%"
    if requester:
        where.append("(u.full_name ILIKE :rq OR u.username ILIKE :rq)")
        p["rq"] = f"%{requester}%"
    if urgency:
        where.append("q.urgency = :urg")
        p["urg"] = urgency
    if date_from:
        where.append("q.created_at >= :df")
        p["df"] = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
    if date_to:
        where.append("q.created_at < :dt")
        p["dt"] = datetime.combine(date_to, datetime.max.time(), tzinfo=timezone.utc)
    w = " AND ".join(where)
    total = (await session.execute(text("SELECT count(*) FROM reagent_requests q LEFT JOIN reagents r ON r.id = q.reagent_id "
                                        "JOIN users u ON u.id = q.requested_by WHERE " + w), p)).scalar_one()
    rows = (await session.execute(text(SELECT + " WHERE " + w + " ORDER BY CASE q.urgency WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 ELSE 2 END, "
                                       "q.created_at DESC LIMIT :lim OFFSET :off"), p)).mappings().all()
    return RequestPage(items=await _outs(session, rows), total=total, limit=limit, offset=offset)


@router.get("/{request_id}", response_model=RequestDetail)
async def get_request(request_id: uuid.UUID, user: User = require("requests.create"), session: AsyncSession = Depends(get_session)):
    """The requester sees their own request; lab assistants see all. Anyone else gets 404."""
    row = (await session.execute(text(SELECT + " WHERE q.id = :id"), {"id": request_id})).mappings().first()
    if row is None or (row["requested_by"] != user.id and user.role != "lab_analyst"):
        raise HTTPException(404, "Request not found")
    out = (await _outs(session, [row]))[0]
    return RequestDetail(**out.model_dump(), events=await _events(session, request_id),
                         allowed_next=sorted(wf.TRANSITIONS[out.status]) if user.role == "lab_analyst" else [])


@router.post("/{request_id}/respond", response_model=RequestDetail)
async def respond(request: Request, request_id: uuid.UUID, body: RespondIn, user: User = require("requests.create"),
                  session: AsyncSession = Depends(get_session)):
    """The requester answers a clarification request; the request goes back to 'under review'."""
    req = await _locked(session, request_id)
    if req.requested_by != user.id:
        raise HTTPException(404, "Request not found")
    if req.status != "needs_clarification":
        raise HTTPException(409, "This request is not waiting for more information from you")
    await wf.add_event(session, req.id, user, "comment", None, None, body.comment)
    await _status_change(session, req, user, "under_review", "Requester provided the requested information", audit.client_ip(request))
    if req.handled_by:
        await notify(session, req.handled_by, f"{user.full_name} answered your clarification request.", "/analyst", kind="request_clarified")
    else:
        await wf.notify_assistants(session, f"{user.full_name} answered a clarification request.", "/analyst", "request_clarified")
    await session.commit()
    return await get_request(request_id, user, session)


# ------------------------------------------------------------------ lab assistant
@router.post("/{request_id}/comment", response_model=RequestDetail)
async def comment(request: Request, request_id: uuid.UUID, body: CommentIn, user: User = require("inventory.manage"),
                  session: AsyncSession = Depends(get_session)):
    req = await _locked(session, request_id)
    await wf.add_event(session, req.id, user, "comment", None, None, body.comment)
    await notify(session, req.requested_by, f"A lab assistant commented on your request: {body.comment[:120]}", "/my-requests",
                 kind="request_comment")
    await audit.log(session, user, "request_comment", str(req.id), ip=audit.client_ip(request))
    await session.commit()
    return await get_request(request_id, user, session)


@router.post("/{request_id}/transition", response_model=RequestDetail)
async def transition(request: Request, request_id: uuid.UUID, body: TransitionIn, user: User = require("inventory.manage"),
                     session: AsyncSession = Depends(get_session)):
    """Move a request along the lifecycle. `fulfilled` is not reachable here - use /fulfil, which records what actually happened."""
    if body.to_status not in wf.TRANSITIONS:
        raise HTTPException(422, f"Unknown status '{body.to_status}'")
    if body.to_status == "fulfilled":
        raise HTTPException(422, "Use POST /requests/{id}/fulfil to mark a request fulfilled")
    if body.to_status in wf.COMMENT_REQUIRED and len((body.comment or "").strip()) < 3:
        raise HTTPException(422, f"A comment is required when moving a request to '{body.to_status}'")
    req = await _locked(session, request_id)
    try:
        wf.check_transition(req.status, body.to_status)       # reject illegal moves before doing any work
    except wf.InvalidTransition as e:
        raise HTTPException(409, str(e))
    ip = audit.client_ip(request)
    prev = req.status
    notice = {
        "under_review": "A lab assistant is reviewing your reagent request.",
        "needs_clarification": f"More information is needed for your reagent request: {(body.comment or '').strip()}",
        "approved": "Your reagent request was approved. This does NOT mean the reagent has been issued yet - you will be told when it is fulfilled.",
        "rejected": f"Your reagent request was rejected: {(body.comment or '').strip()}",
    }[body.to_status]
    if body.to_status == "approved" and (body.reserve_lot_id or body.reserve_quantity):
        if req.reagent_id is None or body.reserve_lot_id is None:
            raise HTTPException(422, "Reserving stock needs a reagent from the register and a lot")
        lot_unit = (await session.get(Reagent, req.reagent_id)).unit
        qty = body.reserve_quantity or _qty_in(req, lot_unit)
        res = await session.execute(text(
            "UPDATE reagent_lots SET reserved_quantity = reserved_quantity + :q, row_version = row_version + 1 "
            "WHERE id = :l AND reagent_id = :r AND availability = 'active' AND (expiry_date IS NULL OR expiry_date > current_date) "
            "AND quantity_available - reserved_quantity >= :q RETURNING id"), {"q": qty, "l": body.reserve_lot_id, "r": req.reagent_id})
        if res.first() is None:
            await session.rollback()
            raise HTTPException(409, "That lot cannot cover the reservation (not enough usable stock, expired, or unavailable).")
        req = await _locked(session, request_id)
        req.reserved_lot_id, req.reserved_quantity = body.reserve_lot_id, qty
        notice += " Stock has been set aside for you."
    if body.to_status == "rejected" and prev == "approved":
        await _release_reservation(session, req)
    if body.to_status == "rejected":
        req.reject_reason = body.comment.strip()
    await _status_change(session, req, user, body.to_status, (body.comment or "").strip() or None, ip, notice)
    await session.commit()
    return await get_request(request_id, user, session)


@router.post("/{request_id}/fulfil", response_model=RequestDetail)
async def fulfil(request: Request, request_id: uuid.UUID, body: FulfilIn, user: User = require("inventory.manage"),
                 session: AsyncSession = Depends(get_session)):
    """Mark an APPROVED request fulfilled. Either issue from a lot (atomic stock decrement) or confirm - against a real,
    in-date lot - that the need has been met. A request for a reagent that is not in the register is fulfilled by note."""
    req = await _locked(session, request_id)
    if req.status != "approved":
        raise HTTPException(409, "Only an approved request can be fulfilled. Approve it first.")
    ip = audit.client_ip(request)
    rid = req.reagent_id          # plain value: ORM attributes are expired after a rollback
    reagent = await session.get(Reagent, rid) if rid else None
    lot_no = None
    if body.issue_from_lot:
        if reagent is None or body.lot_id is None:
            raise HTTPException(422, "Issuing needs a reagent from the register and a lot")
        qty = _qty_in(req, reagent.unit)
        release = float(req.reserved_quantity or 0) if req.reserved_lot_id == body.lot_id else 0.0
        # ONE atomic statement: availability + expiry + stock (net of OTHER people's reservations) + decrement.
        row = (await session.execute(text(
            "UPDATE reagent_lots SET quantity_available = quantity_available - :q, "
            "reserved_quantity = GREATEST(reserved_quantity - :rel, 0), row_version = row_version + 1 "
            "WHERE id = :lot AND reagent_id = :rid AND availability = 'active' AND (expiry_date IS NULL OR expiry_date > current_date) "
            "AND quantity_available - reserved_quantity + :rel >= :q RETURNING lot_no, quantity_available"),
            {"q": qty, "lot": body.lot_id, "rid": req.reagent_id, "rel": release})).first()
        if row is None:
            await session.rollback()
            lot = (await session.execute(text("SELECT reagent_id, expiry_date, availability FROM reagent_lots WHERE id = :i"),
                                         {"i": body.lot_id})).first()
            if lot is None or lot.reagent_id != rid:
                raise HTTPException(409, "That lot does not match the requested reagent.")
            if lot.expiry_date is not None and lot.expiry_date <= date.today():
                raise HTTPException(409, "That lot is expired and cannot be issued.")
            if lot.availability != "active":
                raise HTTPException(409, "That lot is not available (quarantined or unavailable).")
            raise HTTPException(409, "Not enough unreserved stock in that lot.")
        lot_no = row.lot_no
        if req.reserved_lot_id and req.reserved_lot_id != body.lot_id:
            await _release_reservation(session, req)
        else:
            req.reserved_lot_id, req.reserved_quantity = None, 0
        session.add(InventoryTransaction(lot_id=body.lot_id, type="issued", quantity=qty, performed_by=user.id,
                                         issued_to=req.requested_by, reason=f"request {req.id}"))
        req.issued_lot_id = body.lot_id
    elif reagent is not None:
        if body.lot_id is None:
            raise HTTPException(422, "Name the in-date lot that now covers this need, or issue from a lot")
        row = (await session.execute(text(inv.LOT_SQL + " WHERE l.id = :l AND l.reagent_id = :r"),
                                     {"l": body.lot_id, "r": req.reagent_id})).mappings().first()
        if row is None or inv.row_to_lot(row)["usable_quantity"] <= 0:
            raise HTTPException(409, "That lot has no usable stock (expired, unavailable, empty or fully reserved).")
        lot_no = row["lot_no"]
        await _release_reservation(session, req)
    else:
        await _release_reservation(session, req)
    req.fulfilment_note = body.note.strip()
    req.fulfilled_at = datetime.now(timezone.utc)
    await _status_change(session, req, user, "fulfilled", body.note.strip(), ip,
                         "Your reagent request was fulfilled" + (f" (lot {lot_no})." if lot_no else "."))
    await session.commit()
    return await get_request(request_id, user, session)


# ------------------------------------------------------------------ legacy one-click endpoints (kept for existing clients)
@router.post("/{request_id}/issue", response_model=RequestOut)
async def issue(request: Request, request_id: uuid.UUID, body: IssueIn, user: User = require("inventory.manage"),
                session: AsyncSession = Depends(get_session)):
    """Approve (if still open) and fulfil from the chosen lot in one transaction; both steps are recorded separately."""
    req = await _locked(session, request_id)
    if req.status in wf.TERMINAL:
        raise HTTPException(409, f"This request was already {req.status}.")
    if req.status != "approved":
        if req.status == "needs_clarification":
            await _status_change(session, req, user, "under_review", None, audit.client_ip(request))
        await _status_change(session, req, user, "approved", "Approved and issued in one step", audit.client_ip(request))
    await session.flush()
    await fulfil(request, request_id, FulfilIn(note=f"Issued from lot {body.lot_id}", lot_id=body.lot_id, issue_from_lot=True), user, session)
    return await _one(session, request_id)


@router.post("/{request_id}/reject", response_model=RequestOut)
async def reject(request: Request, request_id: uuid.UUID, body: RejectIn, user: User = require("inventory.manage"),
                 session: AsyncSession = Depends(get_session)):
    await transition(request, request_id, TransitionIn(to_status="rejected", comment=body.reason), user, session)
    return await _one(session, request_id)
