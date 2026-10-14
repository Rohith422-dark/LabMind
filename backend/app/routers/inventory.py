import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import require
from app.models.tables import InventoryTransaction, Reagent, ReagentLot, User
from app.services import audit, inventory as inv, llm, request_workflow as wf

router = APIRouter(prefix="/inventory", tags=["inventory"])


class LotOut(BaseModel):
    lot_id: uuid.UUID
    reagent_id: uuid.UUID
    name: str
    cas_number: str | None = None
    formula: str | None = None
    hazard_classes: list[str] = []
    hazard_statements: list[str] = []
    reorder_level: float | None = None
    unit: str | None = None
    lot_no: str
    grade: str | None = None
    capacity: float
    quantity_available: float
    location: str | None = None
    expiry_date: date | None = None
    received_date: date | None = None
    storage_conditions: str | None = None
    supplier: str | None = None
    status: str
    days_remaining: int | None = None
    reserved_quantity: float = 0
    usable_quantity: float = 0
    availability: str = "active"
    row_version: int = 1


class ReagentSummaryOut(BaseModel):
    reagent_id: uuid.UUID
    name: str
    cas_number: str | None = None
    unit: str | None = None
    reorder_level: float | None = None
    storage_conditions: str | None = None
    hazard_classes: list[str] = []
    physical_quantity: float
    usable_quantity: float
    reserved_quantity: float
    expired_quantity: float
    unavailable_quantity: float
    status: str
    status_label: str
    lots: int
    nearest_usable_expiry: date | None = None


class ReagentOut(BaseModel):
    id: uuid.UUID
    name: str
    cas_number: str | None = None
    unit: str | None = None
    model_config = {"from_attributes": True}


class LotIn(BaseModel):
    reagent_id: uuid.UUID | None = None
    reagent_name: str | None = None
    cas_number: str | None = None
    unit: str | None = None
    lot_no: str = Field(min_length=1, max_length=80)
    grade: str | None = None
    capacity: float = Field(gt=0)
    quantity_available: float = Field(ge=0)
    location: str | None = None
    expiry_date: date | None = None
    received_date: date | None = None
    storage_conditions: str | None = None
    supplier: str | None = None

    @model_validator(mode="after")
    def _need_reagent(self):
        if not self.reagent_id and not (self.reagent_name or "").strip():
            raise ValueError("reagent_id or reagent_name is required")
        if self.quantity_available > self.capacity:
            raise ValueError("quantity_available cannot exceed capacity")
        return self


class ReturnIn(BaseModel):
    quantity: float = Field(gt=0)
    reason: str | None = None


class AdjustIn(BaseModel):
    new_quantity: float = Field(ge=0, le=1e9)
    reason: str = Field(min_length=3, max_length=500)
    expected_version: int | None = Field(default=None, ge=1)    # optimistic lock: reject if the lot changed since it was read


class ReceiveIn(BaseModel):
    quantity: float = Field(gt=0, le=1e9)
    reason: str = Field(min_length=3, max_length=500)
    expiry_date: date | None = None                            # set only if the delivery carries a new expiry date


class LotPatch(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)
    lot_no: str | None = Field(default=None, min_length=1, max_length=80)
    expiry_date: date | None = None
    location: str | None = Field(default=None, max_length=120)
    storage_conditions: str | None = None
    availability: str | None = Field(default=None, pattern="^(active|quarantined|unavailable)$")


class DisposeIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class LabelOut(BaseModel):
    reagent_name: str = ""
    cas_number: str = ""
    lot_no: str = ""
    expiry_date: str = ""
    supplier: str = ""


async def _lot_out(session: AsyncSession, lot_id: uuid.UUID) -> LotOut:
    r = (await session.execute(text(inv.LOT_SQL + " WHERE l.id = :id"), {"id": lot_id})).mappings().first()
    if r is None:
        raise HTTPException(404, "Lot not found")
    return LotOut(**inv.row_to_lot(r))


@router.get("", response_model=list[LotOut])
async def list_inventory(name: str | None = None, status: str | None = None, hazard: str | None = None,
                         expiring_soon: bool = False, user: User = require("inventory.view"),
                         session: AsyncSession = Depends(get_session)):
    sql, params = inv.LOT_SQL + " WHERE true", {}
    if name:
        sql += " AND (r.name ILIKE :n OR r.cas_number ILIKE :n OR l.lot_no ILIKE :n)"
        params["n"] = f"%{name}%"
    if hazard:
        sql += " AND (EXISTS (SELECT 1 FROM unnest(r.hazard_classes) h WHERE h ILIKE :hz) OR EXISTS (SELECT 1 FROM unnest(r.hazard_statements) h WHERE h ILIKE :hz))"
        params["hz"] = f"%{hazard}%"
    rows = (await session.execute(text(sql + " ORDER BY r.name, l.expiry_date NULLS LAST"), params)).mappings().all()
    lots = [LotOut(**inv.row_to_lot(r)) for r in rows]
    if status:
        lots = [l for l in lots if l.status == status]
    if expiring_soon:
        lots = [l for l in lots if l.days_remaining is not None and 0 < l.days_remaining <= inv.NEAR_EXPIRY_DAYS]
    return lots


@router.get("/reagents/summary", response_model=list[ReagentSummaryOut])
async def reagent_summary(name: str | None = None, status: str | None = None, user: User = require("inventory.view"),
                          session: AsyncSession = Depends(get_session)):
    """One row per reagent: physical vs usable vs reserved vs expired/unavailable stock and the resulting availability label."""
    rows = await inv.reagent_summaries(session, name)
    return [r for r in rows if not status or r["status"] == status]


@router.get("/reagents", response_model=list[ReagentOut])
async def list_reagents(user: User = require("inventory.view"), session: AsyncSession = Depends(get_session)):
    return (await session.execute(select(Reagent).order_by(Reagent.name))).scalars().all()


async def _tx(session, lot_id, kind, qty, user, reason=None, issued_to=None):
    session.add(InventoryTransaction(lot_id=lot_id, type=kind, quantity=qty, performed_by=user.id,
                                     issued_to=issued_to, reason=reason))


@router.post("/lots", response_model=LotOut, status_code=201)
async def add_lot(request: Request, body: LotIn, user: User = require("inventory.manage"),
                  session: AsyncSession = Depends(get_session)):
    rid = body.reagent_id
    if rid is None:
        name = body.reagent_name.strip()
        rid = (await session.execute(select(Reagent.id).where(Reagent.name.ilike(name)))).scalar()
        if rid is None:
            r = Reagent(name=name, cas_number=body.cas_number, unit=body.unit, supplier=body.supplier)
            session.add(r)
            await session.flush()
            rid = r.id
    elif await session.get(Reagent, rid) is None:
        raise HTTPException(404, "Reagent not found")
    lot = ReagentLot(reagent_id=rid, lot_no=body.lot_no, grade=body.grade, capacity=body.capacity,
                     quantity_available=body.quantity_available, location=body.location, expiry_date=body.expiry_date,
                     received_date=body.received_date or date.today(), storage_conditions=body.storage_conditions,
                     supplier=body.supplier)
    before = await inv.usable_total(session, rid)
    session.add(lot)
    await session.flush()
    await _tx(session, lot.id, "received", body.quantity_available, user, "lot added")
    await _restock_check(session, rid, before)
    await audit.log(session, user, "lot_added", f"{body.lot_no}", {"lot_id": str(lot.id)}, audit.client_ip(request))
    await session.commit()
    return await _lot_out(session, lot.id)


@router.post("/lots/label", response_model=LabelOut)
async def read_label(file: UploadFile = File(...), user: User = require("inventory.manage")):
    data = await file.read(8 * 1024 * 1024)
    try:
        return await llm.extract_from_image(
            data, "Read this reagent bottle label. Return reagent_name, cas_number, lot_no, expiry_date (YYYY-MM-DD), "
                  "supplier. Use empty strings for anything not visible. Never guess.", LabelOut, mock=LabelOut())
    except llm.LLMError as e:
        raise HTTPException(503, str(e))


async def _restock_check(session: AsyncSession, reagent_id: uuid.UUID, usable_before: float) -> None:
    """If this change turned 'nothing usable' into 'usable stock', tell the people waiting for the reagent."""
    if usable_before <= 0 and await inv.usable_total(session, reagent_id) > 0:
        await wf.notify_restocked(session, reagent_id, (await session.get(Reagent, reagent_id)).name)


def _check_version(lot: ReagentLot, expected: int | None) -> None:
    if expected is not None and expected != lot.row_version:
        raise HTTPException(409, f"This lot was changed by someone else (you saw v{expected}, it is now v{lot.row_version}). Reload and retry.")


async def _locked_lot(session: AsyncSession, lot_id: uuid.UUID) -> ReagentLot:
    lot = (await session.execute(select(ReagentLot).where(ReagentLot.id == lot_id).with_for_update())).scalar_one_or_none()
    if lot is None:
        raise HTTPException(404, "Lot not found")
    return lot


@router.post("/lots/{lot_id}/return", response_model=LotOut)
async def return_lot(request: Request, lot_id: uuid.UUID, body: ReturnIn, user: User = require("inventory.manage"),
                     session: AsyncSession = Depends(get_session)):
    lot = await _locked_lot(session, lot_id)
    if float(lot.quantity_available) + body.quantity > float(lot.capacity):
        raise HTTPException(409, "Returned quantity would exceed the lot capacity")
    before = await inv.usable_total(session, lot.reagent_id)
    lot.quantity_available = float(lot.quantity_available) + body.quantity
    lot.row_version += 1
    await _tx(session, lot.id, "returned", body.quantity, user, body.reason)
    await session.flush()
    await _restock_check(session, lot.reagent_id, before)
    await audit.log(session, user, "lot_returned", lot.lot_no, {"quantity": body.quantity}, audit.client_ip(request))
    await session.commit()
    return await _lot_out(session, lot_id)


@router.post("/lots/{lot_id}/adjust", response_model=LotOut)
async def adjust_lot(request: Request, lot_id: uuid.UUID, body: AdjustIn, user: User = require("inventory.manage"),
                     session: AsyncSession = Depends(get_session)):
    lot = await _locked_lot(session, lot_id)
    _check_version(lot, body.expected_version)
    if body.new_quantity > float(lot.capacity):
        raise HTTPException(409, "Quantity cannot exceed the lot capacity")
    if body.new_quantity < float(lot.reserved_quantity):
        raise HTTPException(409, f"{float(lot.reserved_quantity):g} is reserved for approved requests; "
                                 "release or fulfil those before lowering the quantity below it.")
    before = await inv.usable_total(session, lot.reagent_id)
    delta = body.new_quantity - float(lot.quantity_available)
    lot.quantity_available = body.new_quantity
    lot.row_version += 1
    await _tx(session, lot.id, "adjusted", delta, user, body.reason)
    await session.flush()
    await _restock_check(session, lot.reagent_id, before)
    await audit.log(session, user, "lot_adjusted", lot.lot_no, {"delta": delta, "reason": body.reason},
                    audit.client_ip(request))
    await session.commit()
    return await _lot_out(session, lot_id)


@router.post("/lots/{lot_id}/dispose", response_model=LotOut)
async def dispose_lot(request: Request, lot_id: uuid.UUID, body: DisposeIn, user: User = require("inventory.manage"),
                      session: AsyncSession = Depends(get_session)):
    lot = await _locked_lot(session, lot_id)
    if float(lot.reserved_quantity) > 0:
        raise HTTPException(409, "Stock is reserved for approved requests on this lot; release or fulfil them before disposing.")
    qty = float(lot.quantity_available)
    lot.quantity_available = 0
    lot.row_version += 1
    await _tx(session, lot.id, "disposed", qty, user, body.reason)
    await audit.log(session, user, "lot_disposed", lot.lot_no, {"quantity": qty, "reason": body.reason},
                    audit.client_ip(request))
    await session.commit()
    return await _lot_out(session, lot_id)


@router.post("/lots/{lot_id}/receive", response_model=LotOut)
async def receive_stock(request: Request, lot_id: uuid.UUID, body: ReceiveIn, user: User = require("inventory.manage"),
                        session: AsyncSession = Depends(get_session)):
    """Stock actually arrived (or was replaced). The only way quantity goes UP other than a counted adjustment/return,
    and it is relative, so two deliveries booked at the same moment both count."""
    lot = await _locked_lot(session, lot_id)
    if float(lot.quantity_available) + body.quantity > float(lot.capacity):
        raise HTTPException(409, "This would exceed the lot capacity; register the delivery as a new lot instead.")
    before = await inv.usable_total(session, lot.reagent_id)
    lot.quantity_available = float(lot.quantity_available) + body.quantity
    if body.expiry_date:
        lot.expiry_date = body.expiry_date
    lot.row_version += 1
    await _tx(session, lot.id, "received", body.quantity, user, body.reason)
    await session.flush()
    await _restock_check(session, lot.reagent_id, before)
    await audit.log(session, user, "lot_received", lot.lot_no, {"quantity": body.quantity, "reason": body.reason}, audit.client_ip(request))
    await session.commit()
    return await _lot_out(session, lot_id)


@router.patch("/lots/{lot_id}", response_model=LotOut)
async def edit_lot(request: Request, lot_id: uuid.UUID, body: LotPatch, user: User = require("inventory.manage"),
                   session: AsyncSession = Depends(get_session)):
    """Batch number, expiry, location, storage and availability. Needs the version the editor saw; a stale edit is rejected (409)."""
    lot = await _locked_lot(session, lot_id)
    _check_version(lot, body.expected_version)
    before = await inv.usable_total(session, lot.reagent_id)
    changes = body.model_dump(exclude_unset=True, exclude={"expected_version", "reason"})
    if not changes:
        raise HTTPException(422, "Nothing to change")
    if changes.get("availability") not in (None, "active") and float(lot.reserved_quantity) > 0:
        raise HTTPException(409, "Stock is reserved on this lot; release the reservations before making it unavailable.")
    old = {k: str(getattr(lot, k)) for k in changes}
    for k, v in changes.items():
        setattr(lot, k, v)
    lot.row_version += 1
    await session.flush()
    await _restock_check(session, lot.reagent_id, before)
    await audit.log(session, user, "lot_edited", lot.lot_no, {"before": old, "after": {k: str(v) for k, v in changes.items()},
                                                             "reason": body.reason}, audit.client_ip(request))
    await session.commit()
    return await _lot_out(session, lot_id)
