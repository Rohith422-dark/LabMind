import hashlib
import json
from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session_maker
from app.models.tables import AuditLog

GENESIS = "0" * 64
LOCK_KEY = 727001


def _canon(entry: dict) -> str:
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str)


def _hash(prev: str, entry: dict) -> str:
    return hashlib.sha256((prev + _canon(entry)).encode()).hexdigest()


def _entry(user_id, username, role, action, target, details, ip, ts: datetime) -> dict:
    return {
        "user_id": str(user_id) if user_id else None, "username": username, "role": role,
        "action": action, "target": target, "details": details or {}, "ip": ip,
        "timestamp": ts.astimezone(timezone.utc).isoformat(),
    }


def client_ip(request: Request | None) -> str | None:
    return request.client.host if request and request.client else None


async def log(session: AsyncSession, user, action: str, target: str | None = None,
              details: dict | None = None, ip: str | None = None) -> None:
    """Append a hash-chained audit entry inside the caller's transaction."""
    await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LOCK_KEY})
    prev = (await session.execute(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1))).scalar() or GENESIS
    ts = datetime.now(timezone.utc)
    uid = getattr(user, "id", None)
    uname = getattr(user, "username", None)
    role = getattr(user, "role", None)
    e = _entry(uid, uname, role, action, target, details, ip, ts)
    session.add(AuditLog(user_id=uid, username=uname, role=role, action=action, target=target,
                         details=details or {}, ip=ip, timestamp=ts, prev_hash=prev, hash=_hash(prev, e)))
    await session.flush()


async def log_standalone(user, action: str, target: str | None = None,
                         details: dict | None = None, ip: str | None = None) -> None:
    async with session_maker()() as s:
        await log(s, user, action, target, details, ip)
        await s.commit()


async def verify_chain(session: AsyncSession) -> dict:
    rows = (await session.execute(select(AuditLog).order_by(AuditLog.id))).scalars().all()
    prev = GENESIS
    for r in rows:
        e = _entry(r.user_id, r.username, r.role, r.action, r.target, r.details, r.ip, r.timestamp)
        if r.prev_hash != prev or r.hash != _hash(prev, e):
            return {"ok": False, "checked": len(rows), "first_broken_id": r.id}
        prev = r.hash
    return {"ok": True, "checked": len(rows), "first_broken_id": None}
