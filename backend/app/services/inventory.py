"""Inventory helpers shared by the inventory router, chat and troubleshooting."""
import re
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

NEAR_EXPIRY_DAYS = 30


def lot_status(qty: float, reorder_level: float | None, expiry: date | None, today: date | None = None) -> str:
    """green = in date & stocked; amber = expires <=30d or <= reorder level; red = expired or out of stock."""
    today = today or date.today()
    if qty <= 0 or (expiry is not None and expiry <= today):
        return "red"
    if (expiry is not None and expiry <= today + timedelta(days=NEAR_EXPIRY_DAYS)) or \
            (reorder_level is not None and qty <= float(reorder_level)):
        return "amber"
    return "green"


def days_remaining(expiry: date | None, today: date | None = None) -> int | None:
    return None if expiry is None else (expiry - (today or date.today())).days


LOT_SQL = """
SELECT l.id AS lot_id, r.id AS reagent_id, r.name, r.cas_number, r.formula, r.hazard_classes, r.hazard_statements,
       r.reorder_level, r.unit, l.lot_no, l.grade, l.capacity, l.quantity_available, l.location, l.expiry_date,
       l.received_date, l.storage_conditions, COALESCE(l.supplier, r.supplier) AS supplier
FROM reagent_lots l JOIN reagents r ON r.id = l.reagent_id
"""


def row_to_lot(r) -> dict:
    d = dict(r)
    for k in ("capacity", "quantity_available", "reorder_level"):
        if d.get(k) is not None:
            d[k] = float(d[k])
    d["status"] = lot_status(d["quantity_available"], d["reorder_level"], d["expiry_date"])
    d["days_remaining"] = days_remaining(d["expiry_date"])
    return d


async def find_reagent_ids(session: AsyncSession, question: str) -> list:
    """Reagents whose name (or a >=4 char word of it) appears in the text."""
    rows = (await session.execute(text("SELECT id, name, cas_number FROM reagents"))).all()
    q = question.lower()
    hits = []
    for rid, name, cas in rows:
        n = name.lower()
        if n in q or (cas and cas in q) or any(len(w) >= 5 and re.search(rf"\b{re.escape(w)}\b", q) for w in n.split()):
            hits.append(rid)
    return hits


async def lots_for(session: AsyncSession, reagent_ids: list) -> list[dict]:
    if not reagent_ids:
        return []
    rows = (await session.execute(text(LOT_SQL + " WHERE r.id = ANY(:ids) ORDER BY r.name, l.expiry_date"),
                                  {"ids": reagent_ids})).mappings().all()
    return [row_to_lot(r) for r in rows]


async def hazard_note(session: AsyncSession, texts: list[str]) -> str | None:
    """Safety note built from the reagents table (never LLM-generated)."""
    rows = (await session.execute(text(
        "SELECT name, hazard_classes, hazard_statements FROM reagents WHERE cardinality(hazard_statements) > 0"))).all()
    blob = " ".join(texts).lower()
    parts = []
    for name, classes, stmts in rows:
        n = name.lower()
        if re.search(rf"\b{re.escape(n)}\b", blob) or any(len(w) >= 6 and re.search(rf"\b{re.escape(w)}\b", blob) for w in n.split()):
            parts.append(f"{name}: {'; '.join(stmts[:4])}" + (f" ({', '.join(classes[:3])})" if classes else ""))
    if not parts:
        return None
    return "Hazard data from the reagent register - " + " | ".join(parts[:4]) + ". Check the SDS before handling."
