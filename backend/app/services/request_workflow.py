"""Reagent-request lifecycle rules, unit handling and notifications. Pure rules live here; the router only wires HTTP to them.

Lifecycle (enforced on the server, see TRANSITIONS):

    submitted --> under_review --> approved --> fulfilled
         \\            |   \\           |
          \\           |    needs_clarification --(requester answers)--> under_review
           \\__________|__________________\\__ rejected  (terminal)

Approval and fulfilment are deliberately different states: approving a request never touches stock, never claims the
reagent exists, and never "increases" anything. Only `fulfil` moves stock (when issuing from a lot) or records that the
need was actually met.
"""
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import RequestEvent, User
from app.services.notify import notify

OPEN_STATUSES = ("submitted", "under_review", "needs_clarification", "approved")
TERMINAL = ("rejected", "fulfilled")
TRANSITIONS: dict[str, set[str]] = {
    "submitted": {"under_review", "needs_clarification", "approved", "rejected"},
    "under_review": {"needs_clarification", "approved", "rejected"},
    "needs_clarification": {"under_review", "approved", "rejected"},
    "approved": {"fulfilled", "rejected"},
    "rejected": set(),
    "fulfilled": set(),
}
COMMENT_REQUIRED = {"rejected", "needs_clarification"}
STATUS_LABEL = {"submitted": "Submitted", "under_review": "Under review", "needs_clarification": "Needs clarification",
                "approved": "Approved", "rejected": "Rejected", "fulfilled": "Fulfilled"}

_FAMILIES: dict[str, dict[str, float]] = {
    "mass": {"ug": 1e-6, "mg": 1e-3, "g": 1.0, "kg": 1e3},
    "volume": {"uL": 1e-6, "mL": 1e-3, "L": 1.0},
    "amount": {"umol": 1e-6, "mmol": 1e-3, "mol": 1.0},
    "count": {"unit": 1.0, "pcs": 1.0, "vial": 1.0, "bottle": 1.0, "pack": 1.0},
}
_ALIASES = {"ug": "ug", "µg": "ug", "μg": "ug", "mg": "mg", "g": "g", "kg": "kg", "ul": "uL", "µl": "uL", "μl": "uL", "ml": "mL",
            "l": "L", "umol": "umol", "µmol": "umol", "mmol": "mmol", "mol": "mol", "unit": "unit", "units": "unit", "pcs": "pcs",
            "pc": "pcs", "vial": "vial", "vials": "vial", "bottle": "bottle", "bottles": "bottle", "pack": "pack", "packs": "pack"}
UNIT_CHOICES = ["mg", "g", "kg", "uL", "mL", "L", "umol", "mmol", "mol", "unit", "vial", "bottle", "pack"]


def normalize_unit(u: str | None) -> str | None:
    return _ALIASES.get((u or "").strip().lower()) if u else None


def family(u: str) -> str | None:
    return next((f for f, m in _FAMILIES.items() if u in m), None)


def convert(qty: float, src: str, dst: str) -> float | None:
    """qty expressed in `src` -> `dst`, or None when the units are of different kinds (e.g. g vs mL)."""
    f = family(src)
    if f is None or f != family(dst):
        return None
    return qty * _FAMILIES[f][src] / _FAMILIES[f][dst]


def check_transition(current: str, target: str) -> None:
    if target not in TRANSITIONS.get(current, set()):
        raise InvalidTransition(f"A {STATUS_LABEL[current].lower()} request cannot move to {STATUS_LABEL.get(target, target).lower()}.")


class InvalidTransition(Exception):
    pass


async def add_event(session: AsyncSession, request_id: uuid.UUID, actor: User, kind: str, from_status: str | None,
                    to_status: str | None, comment: str | None) -> None:
    session.add(RequestEvent(request_id=request_id, kind=kind, from_status=from_status, to_status=to_status,
                             actor_id=actor.id, comment=(comment or None)))
    await session.flush()


async def notify_assistants(session: AsyncSession, message: str, link: str, kind: str, exclude: uuid.UUID | None = None) -> None:
    for uid in (await session.execute(select(User.id).where(User.role == "lab_analyst"))).scalars():
        if uid != exclude:
            await notify(session, uid, message, link, kind=kind)


async def notify_restocked(session: AsyncSession, reagent_id: uuid.UUID, reagent_name: str) -> None:
    """Tell everyone waiting on this reagent that usable stock now exists."""
    rows = (await session.execute(text(
        "SELECT id, requested_by FROM reagent_requests WHERE reagent_id = :r AND status IN ('submitted','under_review','needs_clarification','approved')"),
        {"r": reagent_id})).all()
    for rid, uid in rows:
        await notify(session, uid, f"{reagent_name} is available again - your open request can now be processed.",
                     "/my-requests", kind="reagent_available")
