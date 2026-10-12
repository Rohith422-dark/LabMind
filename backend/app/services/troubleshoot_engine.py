"""Deterministic narrated-procedure vs SOP comparison (NO LLM in the decision).

Inputs are plain dicts so the engine is trivially unit-testable:
  sop_steps: [{step_no, action, parameters: {name: {value, unit}}, is_critical}]
  narrated:  [{order, action, parameters: {name: {value, unit}}, aligned_step_no | None}]
"""
import re
from dataclasses import dataclass, field
from typing import Any

from app.services import units

FOLLOWED, MISSING, DEVIATION, OUT_OF_ORDER, CONFIRM = "followed", "missing", "deviation", "out_of_order", "confirm"
PRIORITY = {DEVIATION: 4, MISSING: 3, OUT_OF_ORDER: 2, CONFIRM: 1, FOLLOWED: 0}
NON_QUANT = {"reagent", "other"}


@dataclass
class Finding:
    param: str
    kind: str
    expected: float
    actual: float | None
    expected_text: str
    actual_text: str | None
    tolerance: str
    result: str  # ok | deviation | unstated


@dataclass
class Row:
    step_no: int | None
    sop_action: str
    sop_requirement: str
    narrated: str | None
    status: str
    is_critical: bool
    findings: list[Finding] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    note: str | None = None


def _quant(p: Any) -> units.Quantity | None:
    if isinstance(p, dict):
        return units.to_canonical(p.get("value"), p.get("unit")) if p.get("unit") else _bare(p)
    return None


def _bare(p: dict) -> units.Quantity | None:
    try:
        return units.Quantity("cycles", float(str(p.get("value")).replace(",", ".")), str(p.get("value")))
    except (TypeError, ValueError):
        return None


def _named_quant(name: str, p: Any) -> units.Quantity | None:
    q = _quant(p)
    if q is None:
        return None
    # a bare number under a 'cycles' parameter is a count; a bare number elsewhere is unitless -> skip
    if not (isinstance(p, dict) and p.get("unit")) and name != "cycles":
        return None
    return q


def longest_increasing_subsequence(seq: list[int]) -> set[int]:
    """Indices (into seq) that form one longest strictly increasing subsequence."""
    if not seq:
        return set()
    tails: list[int] = []        # indices of smallest tail per length
    prev = [-1] * len(seq)
    for i, v in enumerate(seq):
        lo, hi = 0, len(tails)
        while lo < hi:
            mid = (lo + hi) // 2
            if seq[tails[mid]] < v:
                lo = mid + 1
            else:
                hi = mid
        if lo > 0:
            prev[i] = tails[lo - 1]
        if lo == len(tails):
            tails.append(i)
        else:
            tails[lo] = i
    out, k = set(), tails[-1]
    while k != -1:
        out.add(k)
        k = prev[k]
    return out


def _requirement_text(params: dict) -> str:
    bits = []
    for name, p in (params or {}).items():
        q = _named_quant(name, p)
        bits.append(units.fmt(q.kind, q.value) if q else f"{name}: {p.get('value') if isinstance(p, dict) else p}")
    return ", ".join(bits)


def compare(sop_steps: list[dict], narrated: list[dict],
            overrides: dict[str, tuple[str, float]] | None = None) -> list[Row]:
    by_no = {s["step_no"]: s for s in sop_steps}
    aligned: dict[int, dict] = {}
    extras: list[dict] = []
    for n in sorted(narrated, key=lambda n: n.get("order", 0)):
        no = n.get("aligned_step_no")
        if no in by_no and no not in aligned:
            aligned[no] = n
        else:
            extras.append(n)

    # order check: narrated order vs SOP step number among aligned steps
    ordered = sorted(aligned.items(), key=lambda kv: kv[1].get("order", 0))
    keep = longest_increasing_subsequence([no for no, _ in ordered])
    out_of_order = {ordered[i][0] for i in range(len(ordered)) if i not in keep}

    rows: list[Row] = []
    for s in sorted(sop_steps, key=lambda s: s["step_no"]):
        crit = bool(s.get("is_critical"))
        sop_params = s.get("parameters") or {}
        row = Row(s["step_no"], s["action"], _requirement_text(sop_params), None, FOLLOWED, crit)
        n = aligned.get(s["step_no"])
        if n is None:
            row.status = MISSING
            row.flags.append(MISSING)
            rows.append(row)
            continue
        row.narrated = n["action"]
        n_params = n.get("parameters") or {}
        n_by_kind: dict[str, units.Quantity] = {}
        for name, p in n_params.items():
            q = _named_quant(name, p)
            if q:
                n_by_kind.setdefault(q.kind, q)
        for name, p in sop_params.items():
            if name in NON_QUANT:
                continue
            q = _named_quant(name, p)
            if q is None:
                continue
            tol = units.describe_tolerance(q.kind, overrides)
            act = n_by_kind.get(q.kind)
            if act is None:
                row.findings.append(Finding(name, q.kind, q.value, None, units.fmt(q.kind, q.value), None, tol, "unstated"))
                if CONFIRM not in row.flags:
                    row.flags.append(CONFIRM)
            elif units.within_tolerance(q.kind, q.value, act.value, overrides):
                row.findings.append(Finding(name, q.kind, q.value, act.value, units.fmt(q.kind, q.value),
                                            units.fmt(q.kind, act.value), tol, "ok"))
            else:
                row.findings.append(Finding(name, q.kind, q.value, act.value, units.fmt(q.kind, q.value),
                                            units.fmt(q.kind, act.value), tol, "deviation"))
                if DEVIATION not in row.flags:
                    row.flags.append(DEVIATION)
        if s["step_no"] in out_of_order:
            row.flags.append(OUT_OF_ORDER)
        row.status = max(row.flags, key=PRIORITY.get) if row.flags else FOLLOWED
        rows.append(row)

    for n in extras:
        rows.append(Row(None, "(not in SOP)", "", n["action"], DEVIATION, False,
                        flags=[DEVIATION], note="Step performed that is not in the approved SOP"))
    return rows


def clarifying_questions(rows: list[Row], asked: set[str] | None = None, limit: int = 3) -> list[dict]:
    """Questions ONLY for Missing/Confirm items, critical first, max `limit` per turn."""
    asked = asked or set()
    cands = []
    for r in rows:
        if r.step_no is None:
            continue
        if r.status == MISSING:
            q = f"Step {r.step_no} of the SOP says \"{r.sop_action}\". Did you perform it? If so, how?"
            cands.append((0 if r.is_critical else 1, r.step_no, f"missing:{r.step_no}", q))
        else:
            unstated = [f for f in r.findings if f.result == "unstated"]
            if unstated:
                what = ", ".join(f"{f.param} ({f.expected_text})" for f in unstated)
                q = f"For step {r.step_no} (\"{r.sop_action}\"), the SOP specifies {what}. What did you use?"
                cands.append((0 if r.is_critical else 2, r.step_no, f"confirm:{r.step_no}", q))
    cands.sort()
    return [{"key": k, "step_no": no, "question": q} for _, no, k, q in cands if k not in asked][:limit]


# ---------------------------------------------------------------- heuristic alignment
_STOP = set("the a an and or of to in on at for with by is are was were be then next after before step "
            "into from using use used this that it as i we you your then".split())


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def _tokens(t: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z]{3,}", (t or "").lower()) if w not in _STOP}


def heuristic_align(sop_steps: list[dict], narrated: list[dict], threshold: float = 0.2) -> list[dict]:
    """Best-overlap alignment when no LLM is available (dev mock / LLM failure fallback)."""
    toks = {s["step_no"]: _tokens(s["action"]) for s in sop_steps}
    taken: set[int] = set()
    out = []
    for n in narrated:
        nt = _tokens(n["action"])
        best, score = None, 0.0
        for no, st in toks.items():
            if no in taken or not st or not nt:
                continue
            j = len(nt & st) / len(nt | st)
            if j > score:
                best, score = no, j
        n = dict(n)
        if best is not None and score >= threshold:
            n["aligned_step_no"] = best
            taken.add(best)
        else:
            n["aligned_step_no"] = None
        out.append(n)
    return out


def heuristic_structure(text: str) -> list[dict]:
    """Free narration -> structured steps (one per sentence/clause) with parameters from units.parse()."""
    parts = [p.strip() for p in re.split(r"(?<=[.;])\s+|\n+|\bthen\b|\bafter that\b", text or "") if p and p.strip()]
    steps = []
    for i, p in enumerate(parts, start=1):
        params: dict[str, dict] = {}
        for q in units.parse(p):
            params.setdefault(q.kind, {"value": q.value, "unit": _canon_unit(q.kind)})
        steps.append({"order": i, "action": p.rstrip(". "), "parameters": params, "aligned_step_no": None})
    return steps


def _canon_unit(kind: str) -> str:
    return {"temperature": "°C", "time": "s", "volume": "µL", "speed": "rpm", "mass": "mg",
            "concentration": "M", "flow": "mL/min", "percent": "%", "cycles": "cycles", "ph": "pH"}.get(kind, "")
