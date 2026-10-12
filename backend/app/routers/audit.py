import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import require
from app.models.tables import AuditLog, User
from app.services import audit

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditOut(BaseModel):
    id: int
    username: str | None
    role: str | None
    action: str
    target: str | None
    details: dict
    ip: str | None
    timestamp: datetime
    hash: str
    model_config = {"from_attributes": True}


class VerifyOut(BaseModel):
    ok: bool
    checked: int
    first_broken_id: int | None


def _query(action: str | None, username: str | None):
    q = select(AuditLog).order_by(AuditLog.id.desc())
    if action:
        q = q.where(AuditLog.action == action)
    if username:
        q = q.where(AuditLog.username == username)
    return q


@router.get("", response_model=list[AuditOut])
async def list_audit(action: str | None = None, username: str | None = None,
                     limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0),
                     user: User = require("audit.view"), session: AsyncSession = Depends(get_session)):
    return (await session.execute(_query(action, username).limit(limit).offset(offset))).scalars().all()


@router.get("/export")
async def export_audit(user: User = require("audit.view"), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(_query(None, None))).scalars().all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "timestamp", "username", "role", "action", "target", "details", "ip", "hash"])
    for r in rows:
        w.writerow([r.id, r.timestamp.isoformat(), r.username, r.role, r.action, r.target, r.details, r.ip, r.hash])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=audit_log.csv"})


@router.get("/verify", response_model=VerifyOut)
async def verify(user: User = require("audit.view"), session: AsyncSession = Depends(get_session)):
    return await audit.verify_chain(session)
