"""Evidence validation: the policy that decides which model-proposed claims may be shown as project-specific.

This is a practical, testable grounding policy, NOT a proof of correctness. A model drafts claims, each tagged with a
kind and the numbered passages it relies on. Nothing reaches the user unless it passes these deterministic checks:

  1. cites         every observed/interpretation/hypothesis claim cites at least one passage that was really retrieved
  2. numbers       every number in the claim also occurs in a cited passage (no invented values)
  3. lexical       enough of the claim's content words occur in the cited passages and their source names
                   (a cosine hit alone proves nothing)
  4. quotes        anything in quotation marks is a verbatim substring of a cited passage
  5. conflicts     differing values for the same labelled quantity across documents are reported, not reconciled

Claims failing a check are dropped (and recorded in `rejected` for transparency). If no supported claim survives the
verdict is "insufficient" and the caller must offer the external-search choice instead of answering.

Known limits: lexical support cannot detect a claim that reuses the right words with the wrong meaning, and the
conflict detector only recognises "label: number unit" style statements. Both are documented in the README.
"""
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from app.services.retriever import STOP

Kind = Literal["observed", "interpretation", "hypothesis", "unknown"]
SUPPORT_THRESHOLD = {"observed": 0.6, "interpretation": 0.4, "hypothesis": 0.25}
_WORD = re.compile(r"[a-z][a-z0-9\-]+")
_NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
_CITE = re.compile(r"\[(\d{1,2})\]")
_QUOTE = re.compile(r"[\"“]([^\"”]{12,})[\"”]")


# ----------------------------------------------------------------- model-facing schema
class DraftClaim(BaseModel):
    text: str = Field(description="One self-contained statement. No citation markers inside the text.")
    kind: Kind = Field(description="observed = stated by a recorded measurement/document; interpretation = reasonable "
                                   "inference from the records; hypothesis = possible explanation needing verification; "
                                   "unknown = something the records do not establish.")
    cites: list[int] = Field(default_factory=list, description="Numbers of the context passages that support the claim.")


class Draft(BaseModel):
    claims: list[DraftClaim] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list, description="Facts needed but absent from the records.")
    questions_for_user: list[str] = Field(default_factory=list, description="Parameters/observations to ask the user for.")


@dataclass
class Passage:
    n: int
    source_type: str
    source_id: str
    source_version: int
    label: str
    page: int | None
    section: str | None
    text: str
    cosine: float = 0.0


@dataclass
class Rejected:
    text: str
    kind: str
    reason: str


@dataclass
class Validated:
    kept: list[DraftClaim]
    rejected: list[Rejected]
    verdict: Literal["sufficient", "partial", "insufficient"]
    missing: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)


# ----------------------------------------------------------------- text helpers
def _stem(w: str) -> str:
    for suf in ("ings", "ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def tokens(text: str) -> set[str]:
    return {_stem(w) for w in _WORD.findall(text.lower()) if len(w) > 2 and w not in STOP}


def numbers(text: str) -> set[float]:
    return {float(x) for x in _NUM.findall(_CITE.sub(" ", text))}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def lexical_coverage(question: str, passages: list[Passage]) -> float:
    """Share of the question's content words that appear in the retrieved passages (gate before spending a model call)."""
    q = tokens(question)
    if not q:
        return 0.0
    have: set[str] = set()
    for p in passages:
        have |= tokens(p.text)
    return len(q & have) / len(q)


# ----------------------------------------------------------------- validation
def validate(draft: Draft, passages: list[Passage]) -> Validated:
    by_n = {p.n: p for p in passages}
    kept: list[DraftClaim] = []
    rejected: list[Rejected] = []
    for c in draft.claims:
        text = c.text.strip()
        if not text:
            continue
        if c.kind == "unknown":
            kept.append(DraftClaim(text=text, kind="unknown", cites=[]))
            continue
        cites = sorted({n for n in c.cites if n in by_n})
        if not cites:
            rejected.append(Rejected(text, c.kind, "no valid citation"))
            continue
        cited = [by_n[n] for n in cites]
        blob = " ".join(p.text for p in cited)
        missing_nums = numbers(text) - numbers(blob)
        if missing_nums:
            rejected.append(Rejected(text, c.kind, "value not found in cited passages: "
                                     + ", ".join(f"{x:g}" for x in sorted(missing_nums))))
            continue
        ctoks = tokens(text)
        # the cited source's own name/section are part of what the citation shows the reader, so words from them count
        # as supported context ("the caffeine HPLC method ..." when the passage only says "Column temperature is 30 C").
        # Numbers and quotations are still checked against the passage text alone.
        support_blob = blob + " " + " ".join(f"{p.label} {p.section or ''}" for p in cited)
        support = (len(ctoks & tokens(support_blob)) / len(ctoks)) if ctoks else 1.0
        if support < SUPPORT_THRESHOLD[c.kind]:
            rejected.append(Rejected(text, c.kind, f"insufficient lexical support ({support:.2f})"))
            continue
        bad_quote = next((q for q in _QUOTE.findall(text) if _norm(q) not in _norm(blob)), None)
        if bad_quote:
            rejected.append(Rejected(text, c.kind, "quotation is not verbatim in the cited passages"))
            continue
        kept.append(DraftClaim(text=text, kind=c.kind, cites=cites))

    supported = [c for c in kept if c.kind in ("observed", "interpretation")]
    unknowns = [c for c in kept if c.kind == "unknown"]
    missing = [m.strip() for m in draft.missing_information if m.strip()]
    if not supported:
        verdict = "insufficient"
    elif missing or unknowns or rejected:
        verdict = "partial"
    else:
        verdict = "sufficient"
    return Validated(kept, rejected, verdict, missing, [q.strip() for q in draft.questions_for_user if q.strip()])


# ----------------------------------------------------------------- conflicts between documents
_OPS = re.compile(r"(?:=|:|\bis\b|\bwas\b|\bshould be\b|\bmust be\b)\s*(-?\d+(?:\.\d+)?)\s*(°\s?[CFK]|%|[A-Za-zµ]{1,5}(?:/[A-Za-z]{1,4})?)?")
_LABEL_WORD = re.compile(r"[A-Za-z][A-Za-z\-]+")


def _statements(text: str):
    for m in _OPS.finditer(text):
        before = _LABEL_WORD.findall(text[max(0, m.start() - 60): m.start()])
        words = [w.lower() for w in before if w.lower() not in STOP][-3:]
        if not words:
            continue
        unit = re.sub(r"\s+", "", (m.group(2) or "")).lower()
        yield " ".join(words), float(m.group(1)), unit


def detect_conflicts(passages: list[Passage]) -> list[dict]:
    """Same labelled quantity + unit, different values, in different DOCUMENT passages.
    Experiment records are excluded on purpose: different runs legitimately differ."""
    seen: dict[tuple[str, str], list[dict]] = {}
    for p in passages:
        if p.source_type != "document":
            continue
        for label, value, unit in _statements(p.text):
            seen.setdefault((label, unit), []).append({"value": value, "n": p.n, "source": p.label, "page": p.page,
                                                       "source_id": p.source_id})
    out = []
    for (label, unit), obs in seen.items():
        distinct = {o["value"] for o in obs}
        sources = {(o["source_id"], o["page"]) for o in obs}
        if len(distinct) > 1 and len(sources) > 1:
            dedup = list({(o["value"], o["n"]): o for o in obs}.values())
            out.append({"quantity": label, "unit": unit, "statements": dedup})
    return out


# ----------------------------------------------------------------- rendering
def _marks(cites: list[int]) -> str:
    return "".join(f"[{n}]" for n in cites)


def render(v: Validated, conflicts: list[dict], status_note: str | None = None) -> str:
    """Markdown built ONLY from validated claims, so unsupported text can never leak through the model's own prose."""
    parts: list[str] = []
    if status_note:
        parts.append(status_note)
    groups = (("observed", "**Observed in the project records**"),
              ("interpretation", "**Interpretation** (reasoned from the records, not directly recorded)"),
              ("hypothesis", "**Hypotheses** (possible explanations - NOT verified)"))
    for kind, title in groups:
        items = [c for c in v.kept if c.kind == kind]
        if items:
            parts.append(title + "\n" + "\n".join(f"- {c.text} {_marks(c.cites)}".rstrip() for c in items))
    if conflicts:
        lines = []
        for c in conflicts:
            vals = "; ".join(f"{s['value']:g}{(' ' + c['unit']) if c['unit'] else ''} in {s['source']}"
                             + (f", p.{s['page']}" if s['page'] else "") + f" [{s['n']}]" for s in c["statements"])
            lines.append(f"- {c['quantity']}: {vals}")
        parts.append("**Conflicting sources** (not reconciled - check which document is current)\n" + "\n".join(lines))
    unk = [c.text for c in v.kept if c.kind == "unknown"] + v.missing
    if unk:
        parts.append("**Not established by the project records**\n" + "\n".join(f"- {u}" for u in dict.fromkeys(unk)))
    if v.questions:
        parts.append("**To narrow this down, please provide**\n" + "\n".join(f"- {q}" for q in v.questions))
    return "\n\n".join(parts)
