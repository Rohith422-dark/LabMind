"""Keeps project_chunks (the retrieval index) in lock-step with the sources it was built from.

Invariant: a project_chunks row exists only for a source that is currently live. Replacing, deleting or voiding a source
deletes its chunks in the SAME transaction, so a removed or superseded document can never be retrieved afterwards.
"""
import logging
import uuid

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Conversation, Experiment, Memory, ProjectChunk, ProjectDocument
from app.services import llm
from app.services.chunker import chunk
from app.services.parser import ParsedDoc

log = logging.getLogger("sla.project_index")
MAX_EXPERIMENT_NARRATIVE_WORDS = 300


async def _embed(texts: list[str]) -> list[list[float] | None]:
    """Embeddings are best-effort: if the embedding service is down the text is still keyword-searchable."""
    if not texts:
        return []
    try:
        return await llm.embed(texts, "RETRIEVAL_DOCUMENT")
    except llm.LLMError as e:
        log.warning("embedding unavailable, indexing keyword-only: %s", e)
        return [None] * len(texts)


async def drop_chunks(session: AsyncSession, project_id: uuid.UUID, source_type: str, source_id: uuid.UUID) -> None:
    await session.execute(delete(ProjectChunk).where(
        ProjectChunk.project_id == project_id, ProjectChunk.source_type == source_type, ProjectChunk.source_id == source_id))


# ------------------------------------------------------------------ documents
def doc_label(d: ProjectDocument) -> str:
    return f"{d.title} (v{d.version})" if d.version > 1 else d.title


async def index_document(session: AsyncSession, d: ProjectDocument, parsed: ParsedDoc) -> int:
    await drop_chunks(session, d.project_id, "document", d.id)
    pieces = chunk(parsed)
    vecs = await _embed([p.text for p in pieces])
    for i, (p, v) in enumerate(zip(pieces, vecs)):
        session.add(ProjectChunk(project_id=d.project_id, source_type="document", source_id=d.id, source_version=d.version,
                                 label=doc_label(d), seq=i, page=p.page, section=p.section, text=p.text, embedding=v))
    await session.flush()
    return len(pieces)


# ------------------------------------------------------------------ experiments
def _fmt_param(p: dict) -> str:
    val = p.get("value")
    shown = (f"{val:g}" if isinstance(val, (int, float)) and not isinstance(val, bool) else p.get("text_value") or "n/a")
    unit = f" {p['unit']}" if p.get("unit") else ""
    note = f" ({p['note']})" if p.get("note") else ""
    return f"{p.get('name', '?')} = {shown}{unit}{note}"


def experiment_sections(e: Experiment) -> list[tuple[str, str]]:
    """(section, text) pairs that together contain everything searchable about the record."""
    head = f"Experiment {e.identifier} - {e.title} (record v{e.version}; outcome: {e.outcome}"
    head += f"; performed {e.performed_at.date().isoformat()})." if e.performed_at else ")."
    out: list[tuple[str, str]] = []
    overview = [head]
    if e.objective:
        overview.append(f"Objective: {e.objective}")
    if e.reagents:
        overview.append("Reagents: " + "; ".join(
            " ".join(str(x) for x in (r.get("name"), r.get("lot_no") and f"lot {r['lot_no']}",
                                      r.get("quantity") is not None and f"{r['quantity']:g} {r.get('unit') or ''}".strip())
                     if x) for r in e.reagents) + ".")
    if e.equipment:
        overview.append("Equipment: " + "; ".join(str(x.get("name", x)) if isinstance(x, dict) else str(x) for x in e.equipment) + ".")
    if e.conditions:
        overview.append("Conditions: " + "; ".join(f"{k} = {v}" for k, v in e.conditions.items()) + ".")
    if e.procedure_refs:
        overview.append("Procedure references: " + "; ".join(str(r.get("text") or r.get("document_id")) for r in e.procedure_refs) + ".")
    if e.tags:
        overview.append("Tags: " + ", ".join(e.tags) + ".")
    out.append(("Overview", " ".join(overview)))
    if e.parameters:
        out.append(("Parameters", f"{head} Measured parameters: " + "; ".join(_fmt_param(p) for p in e.parameters) + "."))
    for section, body in (("Observations", e.observations), ("Results", e.results), ("Conclusions", e.conclusions)):
        if body and body.strip():
            words = body.split()
            for i in range(0, len(words), MAX_EXPERIMENT_NARRATIVE_WORDS):
                out.append((section, f"{head} {section}: " + " ".join(words[i:i + MAX_EXPERIMENT_NARRATIVE_WORDS])))
    if e.custom_fields:
        out.append(("Custom fields", f"{head} " + "; ".join(f"{k}: {v}" for k, v in e.custom_fields.items()) + "."))
    return out


async def index_experiment(session: AsyncSession, e: Experiment) -> int:
    await drop_chunks(session, e.project_id, "experiment", e.id)
    if e.voided_at is not None:
        return 0
    sections = experiment_sections(e)
    vecs = await _embed([t for _, t in sections])
    for i, ((sec, t), v) in enumerate(zip(sections, vecs)):
        session.add(ProjectChunk(project_id=e.project_id, source_type="experiment", source_id=e.id, source_version=e.version,
                                 label=f"{e.identifier} - {e.title}", seq=i, page=None, section=sec, text=t, embedding=v))
    await session.flush()
    return len(sections)


# ------------------------------------------------------------------ staleness
async def invalidate_derived(session: AsyncSession, project_id: uuid.UUID, source_type: str, source_id: uuid.UUID) -> None:
    """A source changed or vanished: memories built from it become stale, and the project's chat summaries are rebuilt
    on next use (they may restate the old content)."""
    await session.execute(update(Memory).where(
        Memory.project_id == project_id,
        Memory.source_refs.contains([{"type": source_type, "id": str(source_id)}])).values(stale=True))
    await session.execute(update(Conversation).where(Conversation.project_id == project_id, Conversation.summary.is_not(None))
                          .values(summary_stale=True))
