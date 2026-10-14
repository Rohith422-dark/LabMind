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
        cards.append(Card(label="My open requests", link="/my-requests",
                          value=await _n(session, "SELECT count(*) FROM reagent_requests WHERE requested_by=:u "
                                                  "AND status IN ('submitted','under_review','needs_clarification','approved')", u=user.id)))
        rows = (await session.execute(text(inv.LOT_SQL))).mappings().all()
        counts: dict[str, int] = {}
        for r in rows:
            s = inv.row_to_lot(r)["status"]
            counts[s] = counts.get(s, 0) + 1
        out.lots_by_status = [Slice(name=k, value=v) for k, v in counts.items()]
        cards.append(Card(label="Lots expired or out of stock", link="/inventory", value=counts.get("red", 0)))
    if user.role == "lab_analyst":
        cards.append(Card(label="Requests waiting for you", link="/analyst",
                          value=await _n(session, "SELECT count(*) FROM reagent_requests WHERE status IN ('submitted','under_review')")))
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


# ------------------------------------------------------------------ rich, role-specific overview (all numbers are real rows)
class Stat(BaseModel):
    label: str
    value: int | str
    hint: str | None = None
    link: str | None = None
    tone: str = "blue"           # blue | green | amber | red | purple | slate


class Chart(BaseModel):
    title: str
    kind: str                    # donut | bar
    data: list[Slice]


class Item(BaseModel):
    primary: str
    secondary: str | None = None
    badge: str | None = None
    tone: str = "slate"
    link: str | None = None


class Block(BaseModel):
    title: str
    empty: str
    items: list[Item]
    link: str | None = None


class OverviewOut(BaseModel):
    role: str
    headline: str
    subtitle: str
    stats: list[Stat]
    charts: list[Chart]
    blocks: list[Block]


async def _rows(session: AsyncSession, sql: str, **p):
    return (await session.execute(text(sql), p)).mappings().all()


async def _per_day(session: AsyncSession, sql: str, **p) -> list[Slice]:
    """Last 7 days (oldest first), zero-filled. `sql` must select a date AS d and a count AS n."""
    from datetime import date, timedelta
    got = {r["d"]: int(r["n"]) for r in await _rows(session, sql, **p)}
    days = [date.today() - timedelta(days=i) for i in range(6, -1, -1)]
    return [Slice(name=d.strftime("%a %d"), value=got.get(d, 0)) for d in days]


def _slices(rows, label=lambda x: x) -> list[Slice]:
    return [Slice(name=label(r["k"]), value=int(r["n"])) for r in rows]


OPEN_REQ = "('submitted','under_review','needs_clarification','approved')"


async def _scientist(session: AsyncSession, user: User, first: str, unread: int):
    mine = "SELECT project_id FROM project_members WHERE user_id = :u"
    n = lambda sql: _n(session, sql, u=user.id)  # noqa: E731
    stats = [
        Stat(label="My projects", value=await n("SELECT count(*) FROM project_members m JOIN projects p ON p.id=m.project_id WHERE m.user_id=:u AND p.archived_at IS NULL"), link="/projects", tone="blue"),
        Stat(label="Experiments recorded", value=await n(f"SELECT count(*) FROM experiments WHERE voided_at IS NULL AND project_id IN ({mine})"), hint="in my projects", tone="purple"),
        Stat(label="Documents", value=await n(f"SELECT count(*) FROM project_documents WHERE status='ready' AND project_id IN ({mine})"), hint="project documentation", tone="slate"),
        Stat(label="Open reagent requests", value=await n(f"SELECT count(*) FROM reagent_requests WHERE requested_by=:u AND status IN {OPEN_REQ}"), link="/my-requests", tone="amber"),
        Stat(label="Needs my answer", value=await n("SELECT count(*) FROM reagent_requests WHERE requested_by=:u AND status='needs_clarification'"), hint="clarification requested", link="/my-requests", tone="red"),
        Stat(label="Questions asked", value=await n("SELECT count(*) FROM chat_history WHERE user_id=:u AND created_at > now() - interval '7 days'"), hint="last 7 days", link="/chat", tone="green"),
        Stat(label="Unread notifications", value=unread, tone="slate"),
    ]
    outc = await _rows(session, f"SELECT outcome AS k, count(*) AS n FROM experiments WHERE voided_at IS NULL AND project_id IN ({mine}) GROUP BY 1", u=user.id)
    charts = [
        Chart(title="Experiment outcomes", kind="donut", data=_slices(outc)),
        Chart(title="My assistant questions (7 days)", kind="bar", data=await _per_day(session, "SELECT created_at::date AS d, count(*) AS n FROM chat_history WHERE user_id=:u AND created_at > now() - interval '7 days' GROUP BY 1", u=user.id)),
        Chart(title="My requests by status", kind="donut", data=_slices(await _rows(session, "SELECT status AS k, count(*) AS n FROM reagent_requests WHERE requested_by=:u GROUP BY 1", u=user.id), lambda x: x.replace("_", " "))),
    ]
    blocks = [
        Block(title="Recent experiments", empty="No experiments yet - open a project and record one.", link="/projects", items=[
            Item(primary=f"{r['identifier']} · {r['title']}", secondary=f"{r['pname']} · {r['updated_at']:%d %b %H:%M}", badge=r["outcome"], tone={"success": "green", "failure": "red"}.get(r["outcome"], "slate"), link=f"/projects/{r['project_id']}/experiments")
            for r in await _rows(session, f"SELECT e.identifier, e.title, e.outcome, e.updated_at, e.project_id, p.name AS pname FROM experiments e JOIN projects p ON p.id=e.project_id WHERE e.voided_at IS NULL AND e.project_id IN ({mine}) ORDER BY e.updated_at DESC LIMIT 6", u=user.id)]),
        Block(title="My projects", empty="You are not in any project yet.", link="/projects", items=[
            Item(primary=r["name"], secondary=f"{r['e']} experiments · {r['d']} documents", badge=r["role"], tone="blue", link=f"/projects/{r['id']}")
            for r in await _rows(session, "SELECT p.id, p.name, m.role, (SELECT count(*) FROM experiments x WHERE x.project_id=p.id AND x.voided_at IS NULL) AS e, (SELECT count(*) FROM project_documents d WHERE d.project_id=p.id AND d.status='ready') AS d FROM project_members m JOIN projects p ON p.id=m.project_id WHERE m.user_id=:u AND p.archived_at IS NULL ORDER BY p.updated_at DESC LIMIT 6", u=user.id)]),
        Block(title="Reagents expiring within 30 days", empty="Nothing expiring soon.", link="/inventory", items=[
            Item(primary=r["name"], secondary=f"lot {r['lot_no']} · {float(r['quantity_available']):g} {r['unit'] or ''} left", badge=f"{r['days']} d", tone="amber", link="/inventory")
            for r in await _rows(session, "SELECT r.name, r.unit, l.lot_no, l.quantity_available, (l.expiry_date - current_date) AS days FROM reagent_lots l JOIN reagents r ON r.id=l.reagent_id WHERE l.quantity_available > 0 AND l.expiry_date > current_date AND l.expiry_date <= current_date + 30 ORDER BY l.expiry_date LIMIT 6")]),
        Block(title="Latest updates", empty="No notifications yet.", items=[
            Item(primary=r["message"][:110], secondary=f"{r['created_at']:%d %b %H:%M}", badge=None if r["is_read"] else "new", tone="blue", link=r["link"])
            for r in await _rows(session, "SELECT message, created_at, is_read, link FROM notifications WHERE user_id=:u ORDER BY created_at DESC LIMIT 6", u=user.id)]),
    ]
    return f"Welcome back, {first}", "Your projects, experiments, requests and reagents at a glance.", stats, charts, blocks


async def _lab_analyst(session: AsyncSession, user: User, first: str, unread: int):
    av = await inv.reagent_summaries(session)
    by: dict[str, int] = {}
    for a in av:
        by[a["status"]] = by.get(a["status"], 0) + 1
    lots = [inv.row_to_lot(r) for r in await _rows(session, inv.LOT_SQL)]
    n = lambda sql: _n(session, sql)  # noqa: E731
    stats = [
        Stat(label="Reagents tracked", value=len(av), link="/inventory", tone="blue"),
        Stat(label="Available", value=by.get("available", 0), tone="green"),
        Stat(label="Running low / out", value=by.get("low", 0) + by.get("out_of_stock", 0), hint="needs reordering", link="/inventory", tone="amber"),
        Stat(label="Expired lots", value=sum(1 for l in lots if l["days_remaining"] is not None and l["days_remaining"] <= 0), hint="never usable", link="/analyst", tone="red"),
        Stat(label="Requests waiting", value=await n("SELECT count(*) FROM reagent_requests WHERE status IN ('submitted','under_review')"), link="/analyst", tone="purple"),
        Stat(label="Urgent / high", value=await n(f"SELECT count(*) FROM reagent_requests WHERE status IN {OPEN_REQ} AND urgency IN ('urgent','high')"), tone="red"),
        Stat(label="Approved, awaiting fulfilment", value=await n("SELECT count(*) FROM reagent_requests WHERE status='approved'"), link="/analyst", tone="amber"),
    ]
    charts = [
        Chart(title="Reagent availability", kind="donut", data=[Slice(name=inv.AVAILABILITY_LABEL[k], value=v) for k, v in by.items()]),
        Chart(title="Requests by status", kind="bar", data=_slices(await _rows(session, "SELECT status AS k, count(*) AS n FROM reagent_requests GROUP BY 1 ORDER BY 1"), lambda x: x.replace("_", " "))),
        Chart(title="Stock movements (7 days)", kind="bar", data=await _per_day(session, "SELECT timestamp::date AS d, count(*) AS n FROM inventory_transactions WHERE timestamp > now() - interval '7 days' GROUP BY 1")),
    ]
    expiring = sorted([l for l in lots if l["days_remaining"] is not None and 0 < l["days_remaining"] <= 30 and l["quantity_available"] > 0], key=lambda x: x["days_remaining"])[:7]
    attention = [a for a in av if a["status"] in ("low", "out_of_stock", "expired", "awaiting_restock")][:7]
    blocks = [
        Block(title="Requests needing action", empty="No open requests.", link="/analyst", items=[
            Item(primary=f"{r['reagent_name']} · {float(r['quantity']):g} {r['unit'] or ''}", secondary=f"{r['requester']} · {r['created_at']:%d %b %H:%M}", badge=f"{r['urgency']} · {r['status'].replace('_', ' ')}", tone="red" if r["urgency"] in ("urgent", "high") else "amber", link="/analyst")
            for r in await _rows(session, f"SELECT COALESCE(rg.name, q.reagent_name_text) AS reagent_name, q.quantity, q.unit, q.urgency, q.status, q.created_at, u.full_name AS requester FROM reagent_requests q LEFT JOIN reagents rg ON rg.id=q.reagent_id JOIN users u ON u.id=q.requested_by WHERE q.status IN {OPEN_REQ} ORDER BY CASE q.urgency WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 ELSE 2 END, q.created_at LIMIT 7")]),
        Block(title="Expiring within 30 days", empty="Nothing expiring soon.", link="/inventory", items=[
            Item(primary=f"{l['name']} · lot {l['lot_no']}", secondary=f"{l['quantity_available']:g} {l['unit'] or ''} · {l['location'] or 'no location'}", badge=f"{l['days_remaining']} d", tone="amber", link="/inventory") for l in expiring]),
        Block(title="Low, expired or awaiting restock", empty="All reagents are stocked.", link="/inventory", items=[
            Item(primary=a["name"], secondary=f"usable {a['usable_quantity']:g} {a['unit'] or ''}", badge=a["status_label"], tone="amber" if a["status"] == "low" else "red", link="/inventory") for a in attention]),
        Block(title="Recent stock movements", empty="No movements yet.", items=[
            Item(primary=f"{r['type']} · {float(r['quantity']):g} {r['unit'] or ''} of {r['name']}", secondary=f"lot {r['lot_no']} · {r['who']} · {r['timestamp']:%d %b %H:%M}", badge=r["type"], tone="green" if r["type"] in ("received", "returned") else "slate")
            for r in await _rows(session, "SELECT t.type, t.quantity, t.timestamp, r.name, r.unit, l.lot_no, u.full_name AS who FROM inventory_transactions t JOIN reagent_lots l ON l.id=t.lot_id JOIN reagents r ON r.id=l.reagent_id JOIN users u ON u.id=t.performed_by ORDER BY t.timestamp DESC LIMIT 7")]),
    ]
    return f"Lab overview, {first}", "Stock health, expiries and the requests waiting for you.", stats, charts, blocks


async def _senior(session: AsyncSession, user: User, first: str, unread: int):
    n = lambda sql: _n(session, sql)  # noqa: E731
    up, down = await n("SELECT count(*) FROM chat_history WHERE feedback='up'"), await n("SELECT count(*) FROM chat_history WHERE feedback='down'")
    stats = [
        Stat(label="Effective documents", value=await n("SELECT count(*) FROM documents WHERE status='effective'"), link="/sops", tone="blue"),
        Stat(label="Versions on record", value=await n("SELECT count(*) FROM documents"), hint="incl. superseded / retired", tone="slate"),
        Stat(label="Updated in 30 days", value=await n("SELECT count(*) FROM documents WHERE created_at > now() - interval '30 days'"), tone="green"),
        Stat(label="Open knowledge gaps", value=await n("SELECT count(*) FROM knowledge_gaps WHERE status IN ('open','sop_requested')"), hint="questions the library cannot answer", link="/gaps", tone="red"),
        Stat(label="Questions this week", value=await n("SELECT count(*) FROM chat_history WHERE created_at > now() - interval '7 days'"), tone="purple"),
        Stat(label="Helpful / not helpful", value=f"{up} / {down}", hint="user feedback", tone="amber"),
        Stat(label="Open reagent requests", value=await n(f"SELECT count(*) FROM reagent_requests WHERE status IN {OPEN_REQ}"), tone="slate"),
    ]
    charts = [
        Chart(title="Effective documents by type", kind="donut", data=_slices(await _rows(session, "SELECT doc_type AS k, count(*) AS n FROM documents WHERE status='effective' GROUP BY 1 ORDER BY 1"), lambda x: x.replace("_", " "))),
        Chart(title="Questions asked (7 days)", kind="bar", data=await _per_day(session, "SELECT created_at::date AS d, count(*) AS n FROM chat_history WHERE created_at > now() - interval '7 days' GROUP BY 1")),
        Chart(title="Knowledge gaps by status", kind="donut", data=_slices(await _rows(session, "SELECT status AS k, count(*) AS n FROM knowledge_gaps GROUP BY 1"), lambda x: x.replace("_", " "))),
    ]
    blocks = [
        Block(title="Recently published or updated", empty="No documents yet.", link="/sops", items=[
            Item(primary=f"{r['doc_code']} v{r['version']} · {r['title']}", secondary=f"{r['created_at']:%d %b %Y}" + (f" · {r['change_note']}" if r["change_note"] else ""), badge=r["status"], tone="green" if r["status"] == "effective" else "slate", link=f"/sops/{r['id']}")
            for r in await _rows(session, "SELECT id, doc_code, version, title, status, created_at, change_note FROM documents ORDER BY created_at DESC LIMIT 6")]),
        Block(title="Open knowledge gaps", empty="No open gaps - the library answered everything.", link="/gaps", items=[
            Item(primary=r["question"][:100], secondary=f"asked {r['similar_count']}x", badge=r["status"].replace("_", " "), tone="red", link="/gaps")
            for r in await _rows(session, "SELECT question, similar_count, status FROM knowledge_gaps WHERE status IN ('open','sop_requested') ORDER BY similar_count DESC, created_at DESC LIMIT 6")]),
        Block(title="Most cited documents", empty="No cited answers yet.", items=[
            Item(primary=r["code"], secondary=f"cited in {r['n']} answers")
            for r in await _rows(session, "SELECT s->>'doc_code' AS code, count(*) AS n FROM chat_history, jsonb_array_elements(CASE WHEN jsonb_typeof(sources)='array' THEN sources ELSE '[]'::jsonb END) s WHERE s ? 'doc_code' GROUP BY 1 ORDER BY 2 DESC LIMIT 6")]),
        Block(title="Questions marked not helpful", empty="Nothing flagged.", items=[
            Item(primary=r["question"][:100], secondary=f"{r['created_at']:%d %b %H:%M}", badge="not helpful", tone="red")
            for r in await _rows(session, "SELECT question, created_at FROM chat_history WHERE feedback='down' ORDER BY created_at DESC LIMIT 6")]),
    ]
    return f"Knowledge base overview, {first}", "Document coverage, what people ask, and where the library falls short.", stats, charts, blocks


async def _admin(session: AsyncSession, user: User, first: str, unread: int):
    n = lambda sql: _n(session, sql)  # noqa: E731
    alerts = "('login_failed','access_denied','project_access_denied')"
    stats = [
        Stat(label="Users", value=await n("SELECT count(*) FROM users"), link="/admin/users", tone="blue"),
        Stat(label="Active this week", value=await n("SELECT count(DISTINCT user_id) FROM audit_log WHERE action='login' AND timestamp > now() - interval '7 days'"), hint="distinct logins", tone="green"),
        Stat(label="Failed logins (7 d)", value=await n("SELECT count(*) FROM audit_log WHERE action='login_failed' AND timestamp > now() - interval '7 days'"), tone="red"),
        Stat(label="Access denied (7 d)", value=await n("SELECT count(*) FROM audit_log WHERE action IN ('access_denied','project_access_denied') AND timestamp > now() - interval '7 days'"), tone="amber"),
        Stat(label="Projects", value=await n("SELECT count(*) FROM projects"), tone="purple"),
        Stat(label="Audit entries", value=await n("SELECT count(*) FROM audit_log"), link="/audit", tone="slate"),
        Stat(label="AI questions (7 d)", value=await n("SELECT count(*) FROM chat_history WHERE created_at > now() - interval '7 days'"), tone="blue"),
    ]
    charts = [
        Chart(title="Users by role", kind="donut", data=_slices(await _rows(session, "SELECT role AS k, count(*) AS n FROM users GROUP BY 1"), lambda x: x.replace("_", " "))),
        Chart(title="Audited activity (7 days)", kind="bar", data=await _per_day(session, "SELECT timestamp::date AS d, count(*) AS n FROM audit_log WHERE timestamp > now() - interval '7 days' GROUP BY 1")),
        Chart(title="Top actions (7 days)", kind="bar", data=_slices(await _rows(session, "SELECT action AS k, count(*) AS n FROM audit_log WHERE timestamp > now() - interval '7 days' GROUP BY 1 ORDER BY 2 DESC LIMIT 6"), lambda x: x.replace("_", " "))),
    ]
    blocks = [
        Block(title="Recent audit events", empty="No events yet.", link="/audit", items=[
            Item(primary=r["action"].replace("_", " "), secondary=f"{r['username'] or 'system'} · {r['target'] or ''} · {r['timestamp']:%d %b %H:%M}"[:120], tone="red" if r["action"] in ("login_failed", "access_denied") else "slate", badge="alert" if r["action"] in ("login_failed", "access_denied") else None, link="/audit")
            for r in await _rows(session, "SELECT action, username, target, timestamp FROM audit_log ORDER BY id DESC LIMIT 8")]),
        Block(title="Users", empty="No users.", link="/admin/users", items=[
            Item(primary=r["full_name"], secondary=f"{r['username']} · {r['department'] or ''}", badge=r["role"].replace("_", " "), tone="blue", link="/admin/users")
            for r in await _rows(session, "SELECT full_name, username, department, role FROM users ORDER BY role, full_name LIMIT 8")]),
        Block(title="Security signals (7 days)", empty="No failed logins or denied actions.", link="/audit", items=[
            Item(primary=r["action"].replace("_", " ") + (f" - {r['target']}" if r["target"] else ""), secondary=f"{r['timestamp']:%d %b %H:%M} · {r['ip'] or ''}", badge="alert", tone="red")
            for r in await _rows(session, f"SELECT action, target, timestamp, ip FROM audit_log WHERE action IN {alerts} AND timestamp > now() - interval '7 days' ORDER BY id DESC LIMIT 6")]),
    ]
    return f"Administration overview, {first}", "People, activity and system health.", stats, charts, blocks


@router.get("/overview", response_model=OverviewOut)
async def overview(user: User = require("self.view"), session: AsyncSession = Depends(get_session)):
    parts = (user.full_name or "").split()
    first = (f"{parts[0]} {parts[-1]}" if parts and parts[0].rstrip(".") in ("Dr", "Prof", "Mr", "Ms", "Mrs") and len(parts) > 1 else parts[0] if parts else "there")
    unread = await _n(session, "SELECT count(*) FROM notifications WHERE user_id=:u AND NOT is_read", u=user.id)
    build = {"scientist": _scientist, "lab_analyst": _lab_analyst, "senior_analyst": _senior}.get(user.role, _admin)
    headline, sub, stats, charts, blocks = await build(session, user, first, unread)
    return OverviewOut(role=user.role, headline=headline, subtitle=sub, stats=stats, charts=charts, blocks=blocks)
