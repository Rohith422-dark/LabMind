"""Role-specific dashboard. Every number is computed from real rows; nothing is invented."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import require
from app.models.tables import User
from app.services import inventory as inv

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class Card(BaseModel):
    label: str
    value: int
    link: str | None = None


class Slice(BaseModel):
    name: str
    value: int


class DashboardOut(BaseModel):
    role: str
    cards: list[Card]
    gaps_by_status: list[Slice] = []
    lots_by_status: list[Slice] = []


async def _n(session: AsyncSession, sql: str, **p) -> int:
    return int((await session.execute(text(sql), p)).scalar() or 0)


@router.get("", response_model=DashboardOut)
async def dashboard(user: User = require("self.view"), session: AsyncSession = Depends(get_session)):
    cards: list[Card] = []
    unread = await _n(session, "SELECT count(*) FROM notifications WHERE user_id=:u AND NOT is_read", u=user.id)
    cards.append(Card(label="Unread notifications", value=unread))
    out = DashboardOut(role=user.role, cards=cards)

    if user.role != "admin":
        cards.append(Card(label="Effective documents", link="/sops",
                          value=await _n(session, "SELECT count(*) FROM documents WHERE status='effective'")))
        cards.append(Card(label="My questions asked", link="/chat",
                          value=await _n(session, "SELECT count(*) FROM chat_history WHERE user_id=:u", u=user.id)))
        cards.append(Card(label="My pending requests", link="/my-requests",
                          value=await _n(session, "SELECT count(*) FROM reagent_requests WHERE requested_by=:u AND status='pending'", u=user.id)))
        rows = (await session.execute(text(inv.LOT_SQL))).mappings().all()
        counts: dict[str, int] = {}
        for r in rows:
            s = inv.row_to_lot(r)["status"]
            counts[s] = counts.get(s, 0) + 1
        out.lots_by_status = [Slice(name=k, value=v) for k, v in counts.items()]
        cards.append(Card(label="Lots expired or out of stock", link="/inventory", value=counts.get("red", 0)))
    if user.role == "lab_analyst":
        cards.append(Card(label="Requests waiting for you", link="/analyst",
                          value=await _n(session, "SELECT count(*) FROM reagent_requests WHERE status='pending'")))
    if user.role == "senior_analyst":
        cards.append(Card(label="Open knowledge gaps", link="/gaps",
                          value=await _n(session, "SELECT count(*) FROM knowledge_gaps WHERE status IN ('open','sop_requested')")))
        g = (await session.execute(text("SELECT status, count(*) FROM knowledge_gaps GROUP BY status"))).all()
        out.gaps_by_status = [Slice(name=s, value=int(c)) for s, c in g]
    if user.role in ("senior_analyst", "admin"):
        cards.append(Card(label="Audit entries", link="/audit", value=await _n(session, "SELECT count(*) FROM audit_log")))
    if user.role == "admin":
        cards.append(Card(label="Users", link="/admin/users", value=await _n(session, "SELECT count(*) FROM users")))
    return out
