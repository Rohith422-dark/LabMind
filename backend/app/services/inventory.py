"""Inventory helpers shared by the inventory router, chat and troubleshooting."""
import re
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

NEAR_EXPIRY_DAYS = 30


def is_expired(expiry: date | None, today: date | None = None) -> bool:
    return expiry is not None and expiry <= (today or date.today())


def usable_quantity(qty: float, reserved: float, expiry: date | None, availability: str = "active",
                    today: date | None = None) -> float:
    """Stock that can actually be issued: never expired, never quarantined/unavailable, minus what is reserved."""
    if availability != "active" or is_expired(expiry, today):
        return 0.0
    return max(float(qty) - float(reserved or 0), 0.0)


def lot_status(qty: float, reorder_level: float | None, expiry: date | None, today: date | None = None,
               availability: str = "active") -> str:
    """green = in date & stocked; amber = expires <=30d or <= reorder level; red = expired, out of stock or not available."""
    today = today or date.today()
    if qty <= 0 or availability != "active" or (expiry is not None and expiry <= today):
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
       l.received_date, l.storage_conditions, COALESCE(l.supplier, r.supplier) AS supplier,
       l.reserved_quantity, l.availability, l.row_version
FROM reagent_lots l JOIN reagents r ON r.id = l.reagent_id
"""


def row_to_lot(r) -> dict:
    d = dict(r)
    for k in ("capacity", "quantity_available", "reorder_level", "reserved_quantity"):
        if d.get(k) is not None:
            d[k] = float(d[k])
    d["status"] = lot_status(d["quantity_available"], d["reorder_level"], d["expiry_date"], availability=d["availability"])
    d["usable_quantity"] = usable_quantity(d["quantity_available"], d["reserved_quantity"], d["expiry_date"], d["availability"])
    d["days_remaining"] = days_remaining(d["expiry_date"])
    return d


AVAILABILITY_LABEL = {"available": "Available", "low": "Running low", "out_of_stock": "Out of stock", "expired": "Expired",
                      "unavailable": "Unavailable", "awaiting_restock": "Awaiting restocking"}


def summarise_reagent(lots: list[dict], reorder_level: float | None, has_approved_request: bool) -> dict:
    """Physical vs usable vs reserved vs expired/unavailable stock for one reagent, and the label derived from them.

    physical  = everything on the shelf (all lots, incl. expired and quarantined)
    expired   = quantity in lots past their expiry date  (never counted as usable)
    unavailable = in-date quantity in quarantined/unavailable lots (never counted as usable)
    reserved  = held for approved requests (in-date, active lots)
    usable    = in-date, active, minus reserved
    """
    physical = sum(l["quantity_available"] for l in lots)
    expired = sum(l["quantity_available"] for l in lots if is_expired(l["expiry_date"]))
    unavailable = sum(l["quantity_available"] for l in lots if not is_expired(l["expiry_date"]) and l["availability"] != "active")
    reserved = sum(l["reserved_quantity"] for l in lots if not is_expired(l["expiry_date"]) and l["availability"] == "active")
    usable = sum(l["usable_quantity"] for l in lots)
    if not lots:
        status = "unavailable"
    elif usable > 0:
        status = "low" if reorder_level is not None and usable <= float(reorder_level) else "available"
    elif has_approved_request:
        status = "awaiting_restock"
    elif physical > 0 and expired == physical:
        status = "expired"
    elif unavailable > 0:
        status = "unavailable"
    else:
        status = "out_of_stock"
    soonest = min((l["expiry_date"] for l in lots if l["usable_quantity"] > 0 and l["expiry_date"]), default=None)
    return {"physical_quantity": physical, "usable_quantity": usable, "reserved_quantity": reserved, "expired_quantity": expired,
            "unavailable_quantity": unavailable, "status": status, "status_label": AVAILABILITY_LABEL[status],
            "lots": len(lots), "nearest_usable_expiry": soonest}


async def reagent_summaries(session: AsyncSession, name: str | None = None) -> list[dict]:
    where, params = "", {}
    if name:
        where, params = " WHERE r.name ILIKE :n OR r.cas_number ILIKE :n", {"n": f"%{name}%"}
    reagents = (await session.execute(text(
        "SELECT r.id, r.name, r.cas_number, r.unit, r.reorder_level, r.storage_conditions, r.hazard_classes FROM reagents r"
        + where + " ORDER BY r.name"), params)).mappings().all()
    lots_by: dict = {}
    for row in (await session.execute(text(LOT_SQL))).mappings().all():
        d = row_to_lot(row)
        lots_by.setdefault(d["reagent_id"], []).append(d)
    approved = set((await session.execute(text(
        "SELECT DISTINCT reagent_id FROM reagent_requests WHERE status = 'approved' AND reagent_id IS NOT NULL"))).scalars())
    out = []
    for r in reagents:
        lots = lots_by.get(r["id"], [])
        s = summarise_reagent(lots, float(r["reorder_level"]) if r["reorder_level"] is not None else None, r["id"] in approved)
        out.append({"reagent_id": r["id"], "name": r["name"], "cas_number": r["cas_number"], "unit": r["unit"],
                    "reorder_level": float(r["reorder_level"]) if r["reorder_level"] is not None else None,
                    "storage_conditions": r["storage_conditions"], "hazard_classes": r["hazard_classes"] or [], **s})
    return out


async def usable_total(session: AsyncSession, reagent_id) -> float:
    rows = (await session.execute(text(LOT_SQL + " WHERE r.id = :r"), {"r": reagent_id})).mappings().all()
    return sum(row_to_lot(r)["usable_quantity"] for r in rows)


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


_GENERIC = {"reference", "standard", "solution", "buffer", "grade", "hplc", "anhydrous", "pellets"}
_BENIGN = {"water"}


def _distinctive(name: str) -> str | None:
    """'Caffeine reference standard' -> 'caffeine'; 'Water (HPLC grade)' -> None (benign, appears everywhere)."""
    base = re.sub(r"\([^)]*\)", " ", name.lower())
    words = [w for w in re.findall(r"[a-z0-9-]+", base) if w not in _GENERIC]
    phrase = " ".join(words).strip()
    return None if not phrase or phrase in _BENIGN else phrase


async def hazard_note(session: AsyncSession, texts: list[str]) -> str | None:
    """Safety note built from the reagents table (never LLM-generated)."""
    rows = (await session.execute(text(
        "SELECT name, hazard_classes, hazard_statements FROM reagents WHERE cardinality(hazard_statements) > 0"))).all()
    blob = " ".join(texts).lower()
    parts = []
    for name, classes, stmts in rows:
        key = _distinctive(name)
        if key and re.search(r"\b" + re.escape(key) + r"\b", blob):
            parts.append(f"{name}: {'; '.join(stmts[:4])}" + (f" ({', '.join(classes[:3])})" if classes else ""))
    if not parts:
        return None
    return "Hazard data from the reagent register - " + " | ".join(parts[:4]) + ". Check the SDS before handling."


# ------------------------------------------------------------------ live register context for the AI assistant
REGISTER_RE = re.compile(   # clear signals that the question is about what the lab HAS, not about a procedure
    r"\b(reagents?|chemicals?|ingredients?|compounds?|stock|in stock|inventory|register|lots?|batch(?:es)?|expir\w*|shelf life|running low|low on|"
    r"out of stock|reorder|hazard\w*|flammable|toxic|corrosive|irritant|supplier|vendor|CAS|formula|do we have|do you have|have we got|"
    r"how much .{0,40}(left|remain\w*|do we)|how many .{0,30}(left|bottles|lots))\b", re.I)
PROCEDURE_RE = re.compile(r"\b(how (?:do|to|should|can) (?:i|we|you)|procedure|steps?|calibrat\w*|prepar\w*|protocol|sop|troubleshoot\w*|operate|clean\w*|run)\b", re.I)
HAZARD_WORDS = ("flammable", "toxic", "corrosive", "irritant", "oxidi", "carcinogen", "explosive", "health hazard", "environment", "acute")
LOCATION_RE = re.compile(r"\b(where|stored|store|storage|location|shelf|fridge|freezer|cabinet|cold room)\b", re.I)
HAZARD_RE = re.compile(r"\b(hazard\w*|flammable|toxic|corrosive|irritant|oxidi\w*|carcinogen\w*|explosive|safety|sds|ghs|dangerous)\b", re.I)


def _fmt_lot(l: dict) -> str:
    exp = f"expires {l['expiry_date']} ({l['days_remaining']} d)" if l["expiry_date"] else "no expiry date"
    flag = "EXPIRED" if (l["days_remaining"] is not None and l["days_remaining"] <= 0) else l["availability"].upper() if l["availability"] != "active" else ""
    return (f"lot {l['lot_no']}{' grade ' + l['grade'] if l.get('grade') else ''}: {l['quantity_available']:g}/{l['capacity']:g} {l['unit'] or ''}, "
            f"usable {l['usable_quantity']:g}, reserved {l['reserved_quantity']:g}, location {l['location'] or 'n/a'}, {exp}{' [' + flag + ']' if flag else ''}")


async def register_context(session: AsyncSession, question: str) -> dict | None:
    """Live data from the reagent register relevant to the question, as plain text for the model, plus the lots table.
    Returns None when the question is not about reagents/stock at all."""
    ids = await find_reagent_ids(session, question)
    # a reagent NAME alone is not enough ("how do I run the methanol gradient?" is an SOP question); stock/hazard wording is
    if not (REGISTER_RE.search(question) or (ids and not PROCEDURE_RE.search(question))):
        return None
    summaries = {s["reagent_id"]: s for s in await reagent_summaries(session)}
    detail = (await session.execute(text(
        "SELECT id, name, cas_number, formula, unit, supplier, storage_conditions, reorder_level, hazard_classes, hazard_statements FROM reagents"
        " WHERE id = ANY(:ids) ORDER BY name"), {"ids": ids[:6]})).mappings().all() if ids else []
    lots = await lots_for(session, ids[:6]) if ids else []
    parts: list[str] = []
    for r in detail:
        sm = summaries[r["id"]]
        parts.append(
            f"REAGENT {r['name']} | CAS {r['cas_number'] or 'n/a'} | formula {r['formula'] or 'n/a'} | supplier {r['supplier'] or 'n/a'} | availability: {sm['status_label']} | "
            f"physical {sm['physical_quantity']:g} {r['unit'] or ''}, usable {sm['usable_quantity']:g}, reserved {sm['reserved_quantity']:g}, expired {sm['expired_quantity']:g} | "
            f"reorder level {r['reorder_level'] if r['reorder_level'] is not None else 'n/a'} | storage: {r['storage_conditions'] or 'n/a'} | "
            f"hazard classes: {', '.join(r['hazard_classes'] or []) or 'none recorded'} | hazard statements: {'; '.join((r['hazard_statements'] or [])[:6]) or 'none recorded'}")
        parts += ["  " + _fmt_lot(l) for l in lots if l["reagent_id"] == r["id"]]
    allsum = list(summaries.values())
    by: dict[str, int] = {}
    for s in allsum:
        by[s["status_label"]] = by.get(s["status_label"], 0) + 1
    alll = [row_to_lot(r) for r in (await session.execute(text(LOT_SQL))).mappings().all()]
    soon = sorted([l for l in alll if l["days_remaining"] is not None and 0 < l["days_remaining"] <= 30 and l["quantity_available"] > 0], key=lambda x: x["days_remaining"])[:12]
    expired = [l for l in alll if l["days_remaining"] is not None and l["days_remaining"] <= 0][:12]
    attention = [s for s in allsum if s["status"] in ("low", "out_of_stock", "awaiting_restock")][:12]
    parts.append(f"REGISTER OVERVIEW: {len(allsum)} reagents; " + ", ".join(f"{k}: {v}" for k, v in sorted(by.items())))
    if soon:
        parts.append("EXPIRING WITHIN 30 DAYS: " + " ; ".join(f"{l['name']} {_fmt_lot(l)}" for l in soon))
    if expired:
        parts.append("EXPIRED LOTS (never usable): " + " ; ".join(f"{l['name']} lot {l['lot_no']} expired {l['expiry_date']}" for l in expired))
    if attention:
        parts.append("LOW / OUT OF STOCK / AWAITING RESTOCK: " + " ; ".join(f"{s['name']} ({s['status_label']}, usable {s['usable_quantity']:g} {s['unit'] or ''})" for s in attention))
    if HAZARD_RE.search(question) or LOCATION_RE.search(question) or not ids:
        want = [w for w in HAZARD_WORDS if w in question.lower()]
        cat = (await session.execute(text("SELECT id, name, hazard_classes, storage_conditions FROM reagents ORDER BY name"))).mappings().all()
        lines = []
        for r in cat:
            hz = [h for h in (r["hazard_classes"] or [])]
            if want and not any(w in " ".join(hz).lower() for w in want):
                continue
            locs = sorted({l["location"] for l in alll if l["reagent_id"] == r["id"] and l["location"]})
            lines.append(f"{r['name']}: hazards {', '.join(hz) or 'none recorded'}; storage {r['storage_conditions'] or 'n/a'}; locations {', '.join(locs) or 'n/a'}")
        if lines:
            parts.append(("REAGENTS MATCHING HAZARD FILTER (" + ", ".join(want) + ")" if want else "REAGENT CATALOGUE (hazards, storage, locations)") + ":\n" + "\n".join(lines[:60]))
    return {"text": "\n".join(parts), "lots": [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in l.items() if k != "hazard_statements"} for l in lots],
            "names": [r["name"] for r in detail]}
