import json
import re
import uuid
from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session, session_maker
from app.deps import require
from app.limiter import limiter
from app.models.tables import Document, SopStep, TroubleshootingSession, User
from app.prompts.system_prompt import build_context
from app.prompts.troubleshoot_prompt import ALIGN_PROMPT, DIAGNOSE_PROMPT, STRUCTURE_PROMPT
from app.services import audit, llm, rag, retriever
from app.services import troubleshoot_engine as eng
from app.services.step_extractor import Param, params_to_dict

router = APIRouter(prefix="/troubleshoot", tags=["troubleshoot"])


class StartIn(BaseModel):
    document_id: uuid.UUID | None = None   # None = auto-detect from the symptom
    symptom: str = Field(min_length=3, max_length=1000)
    narration: str = Field(min_length=3, max_length=6000)


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class NarratedStep(BaseModel):
    order: int
    action: str
    parameters: list[Param] = []
    reagent: str | None = None
    lot: str | None = None


class StructuredOut(BaseModel):
    steps: list[NarratedStep] = []


class Alignment(BaseModel):
    order: int
    aligned_step_no: int | None = None


class AlignOut(BaseModel):
    alignments: list[Alignment] = []


class Cause(BaseModel):
    rank: int
    cause: str
    evidence: str
    linked_step_no: int | None = None
    guide_citation: int | None = None


class Diagnosis(BaseModel):
    causes: list[Cause] = []
    next_actions: list[str] = []
    deviation_advice: str | None = None


def _ev(**kw) -> str:
    return json.dumps(kw, default=str) + "\n"


def _stream(gen):
    return StreamingResponse(gen, media_type="application/x-ndjson", headers={"Cache-Control": "no-store"})


async def _sop_steps(session: AsyncSession, document_id: uuid.UUID) -> list[dict]:
    rows = (await session.execute(select(SopStep).where(SopStep.document_id == document_id)
                                  .order_by(SopStep.step_no))).scalars().all()
    return [{"step_no": s.step_no, "action": s.action, "parameters": s.parameters or {},
             "is_critical": s.is_critical} for s in rows]


async def _structure_and_align(text_in: str, sop_steps: list[dict], start_order: int) -> list[dict]:
    """Free text -> structured, SOP-aligned narrated steps (LLM, with deterministic fallback)."""
    fallback = eng.heuristic_structure(text_in)
    try:
        ref = "\n".join(f"{x['step_no']}. {x['action']}" for x in sop_steps)
        s = await llm.generate_structured(f"SOP steps (for granularity only):\n{ref}\n\nScientist's account:\n{text_in}",
                                          StructuredOut, system=STRUCTURE_PROMPT,
                                          mock=StructuredOut(steps=[NarratedStep(order=f["order"], action=f["action"])
                                                                    for f in fallback]))
        steps = [{"order": n.order, "action": n.action, "parameters": params_to_dict(n.parameters),
                  "aligned_step_no": None} for n in s.steps]
        if llm.mock_enabled() or not steps:
            steps = fallback
    except llm.LLMError:
        steps = fallback
    try:
        sop_txt = "\n".join(f"{s['step_no']}. {s['action']}" for s in sop_steps)
        nar_txt = "\n".join(f"{n['order']}. {n['action']}" for n in steps)
        a = await llm.generate_structured(f"SOP steps:\n{sop_txt}\n\nNarrated steps:\n{nar_txt}", AlignOut,
                                          system=ALIGN_PROMPT, mock=AlignOut(alignments=[]))
        if llm.mock_enabled():
            raise llm.LLMError("mock")
        valid = {s["step_no"] for s in sop_steps}
        used: set[int] = set()
        by_order = {x.order: x.aligned_step_no for x in a.alignments}
        for n in steps:
            no = by_order.get(n["order"])
            if no in valid and no not in used:
                n["aligned_step_no"] = no
                used.add(no)
    except llm.LLMError:
        steps = eng.heuristic_align(sop_steps, steps)
    for n in steps:
        n["order"] = start_order + n["order"] - 1
    return steps


def _merge(existing: list[dict], incoming: list[dict], sop_steps: list[dict], slot: bool) -> list[dict]:
    """Merge new narrated steps. Later-turn clarifications are slotted by SOP position so that answering
    'I did step 3 after all' does not look out-of-order."""
    out = [dict(e) for e in existing]
    for n in incoming:
        no = n.get("aligned_step_no")
        n = dict(n)
        if no is not None:
            out = [e for e in out if e.get("aligned_step_no") != no]
            if slot:
                before = [e["order"] for e in out if e.get("aligned_step_no") is not None and e["aligned_step_no"] < no]
                n["order"] = (max(before) + 0.5) if before else 0.5
        out.append(n)
    out.sort(key=lambda e: e["order"])
    for i, e in enumerate(out, start=1):
        e["order"] = i
    return out


def _rows_json(rows: list[eng.Row]) -> list[dict]:
    return [asdict(r) for r in rows]


async def _recompute(sess: TroubleshootingSession, sop_steps: list[dict]):
    rows = eng.compare(sop_steps, sess.narrated_steps)
    asked = {q["key"] for q in (sess.questions_asked or [])}
    qs = eng.clarifying_questions(rows, asked)
    sess.comparison = _rows_json(rows)
    sess.questions_asked = (sess.questions_asked or []) + [{**q, "answered": False} for q in qs]
    return rows, qs


def _doc_json(d: Document) -> dict:
    return {"id": str(d.id), "doc_code": d.doc_code, "version": d.version, "title": d.title, "status": d.status}


@router.post("/start")
@limiter.limit("20/minute")
async def start(request: Request, body: StartIn, user: User = require("knowledge.use")):
    async def gen():
        try:
            async with session_maker()() as s:
                yield _ev(type="stage", stage="Parsing your procedure")
                doc: Document | None = None
                if body.document_id:
                    doc = await s.get(Document, body.document_id)
                    if doc is None or doc.status != "effective":
                        yield _ev(type="error", message="That SOP is not an effective, approved document.")
                        return
                else:
                    try:
                        qv = await llm.embed_one(body.symptom + " " + body.narration[:300], "RETRIEVAL_QUERY")
                    except llm.LLMError as e:
                        yield _ev(type="error", message=str(e))
                        return
                    hits = await retriever.retrieve(s, qv, body.symptom, k=6, doc_types=("SOP", "protocol"))
                    for h in hits:
                        if h["cosine"] < get_settings().vector_min_score:
                            continue
                        steps_n = (await s.execute(text("SELECT count(*) FROM sop_steps WHERE document_id=:d"),
                                                   {"d": h["document_id"]})).scalar()
                        if steps_n:
                            doc = await s.get(Document, h["document_id"])
                            break
                    if doc is None:
                        gid = await rag.record_gap(user, body.symptom)
                        yield _ev(type="no_sop", gap_id=str(gid))
                        yield _ev(type="done")
                        return
                sop_steps = await _sop_steps(s, doc.id)
                if not sop_steps:
                    yield _ev(type="error", message=f"{doc.doc_code} has no structured steps, so it cannot be compared. "
                                                    "Choose another SOP.")
                    return
                yield _ev(type="stage", stage=f"Aligning to {doc.doc_code} v{doc.version}")
                narrated = await _structure_and_align(body.narration, sop_steps, 1)
                yield _ev(type="stage", stage="Checking parameters")
                sess = TroubleshootingSession(user_id=user.id, document_id=doc.id, symptom=body.symptom,
                                              narrated_steps=_merge([], narrated, sop_steps, slot=False),
                                              conversation=[{"role": "user", "content": body.narration}],
                                              questions_asked=[], comparison=[])
                s.add(sess)
                await s.flush()
                rows, qs = await _recompute(sess, sop_steps)
                await audit.log(s, user, "troubleshoot_started", f"{doc.doc_code} v{doc.version}",
                                {"session_id": str(sess.id), "symptom": body.symptom[:200]}, audit.client_ip(request))
                await s.commit()
                yield _ev(type="session", session_id=str(sess.id), document=_doc_json(doc))
                yield _ev(type="comparison", rows=_rows_json(rows), narrated=sess.narrated_steps)
                yield _ev(type="questions", questions=qs)
                yield _ev(type="done")
        except Exception:  # noqa: BLE001
            rag.log.exception("troubleshoot start failed")
            yield _ev(type="error", message="Something went wrong. Please try again.")

    return _stream(gen())


async def _own(session: AsyncSession, sid: uuid.UUID, user: User) -> TroubleshootingSession:
    sess = await session.get(TroubleshootingSession, sid)
    if sess is None or sess.user_id != user.id:
        raise HTTPException(404, "Session not found")
    return sess


@router.post("/{session_id}/message")
@limiter.limit("30/minute")
async def message(request: Request, session_id: uuid.UUID, body: MessageIn, user: User = require("knowledge.use")):
    async def gen():
        try:
            async with session_maker()() as s:
                sess = await _own(s, session_id, user)
                doc = await s.get(Document, sess.document_id)
                sop_steps = await _sop_steps(s, doc.id)
                yield _ev(type="stage", stage="Parsing your procedure")
                incoming = await _structure_and_align(body.text, sop_steps, 1)
                yield _ev(type="stage", stage=f"Aligning to {doc.doc_code} v{doc.version}")
                sess.narrated_steps = _merge(sess.narrated_steps, incoming, sop_steps, slot=True)
                sess.conversation = (sess.conversation or []) + [{"role": "user", "content": body.text}]
                for q in sess.questions_asked or []:
                    q["answered"] = True if any(
                        n.get("aligned_step_no") == q["step_no"] for n in sess.narrated_steps) else q.get("answered", False)
                yield _ev(type="stage", stage="Checking parameters")
                rows, qs = await _recompute(sess, sop_steps)
                await s.commit()
                yield _ev(type="comparison", rows=_rows_json(rows), narrated=sess.narrated_steps)
                yield _ev(type="questions", questions=qs)
                yield _ev(type="done")
        except HTTPException as e:
            yield _ev(type="error", message=e.detail)
        except Exception:  # noqa: BLE001
            rag.log.exception("troubleshoot message failed")
            yield _ev(type="error", message="Something went wrong. Please try again.")

    return _stream(gen())


def _mock_diagnosis(rows: list[eng.Row], n_guide: int) -> Diagnosis:
    bad = sorted((r for r in rows if r.status in (eng.DEVIATION, eng.MISSING, eng.OUT_OF_ORDER) and r.step_no),
                 key=lambda r: (not r.is_critical, r.step_no))
    causes = []
    for i, r in enumerate(bad, start=1):
        if r.status == eng.MISSING:
            what = "was not performed"
        elif r.status == eng.OUT_OF_ORDER:
            what = "was performed out of sequence"
        else:
            f = next((f for f in r.findings if f.result == "deviation"), None)
            what = f"deviated ({f.param}: SOP {f.expected_text}, used {f.actual_text})" if f else "deviated"
        causes.append(Cause(rank=i, cause=f"Step {r.step_no} {what}: {r.sop_action}", evidence=r.sop_requirement or "SOP step",
                            linked_step_no=r.step_no, guide_citation=1 if n_guide else None))
    return Diagnosis(causes=causes, next_actions=[f"Repeat step {c.linked_step_no} exactly as the SOP specifies." for c in causes[:3]],
                     deviation_advice=None)


@router.post("/{session_id}/diagnose")
@limiter.limit("10/minute")
async def diagnose(request: Request, session_id: uuid.UUID, user: User = require("knowledge.use"),
                   session: AsyncSession = Depends(get_session)):
    sess = await _own(session, session_id, user)
    doc = await session.get(Document, sess.document_id)
    sop_steps = await _sop_steps(session, doc.id)
    rows = eng.compare(sop_steps, sess.narrated_steps)
    problems = [r for r in rows if r.status in (eng.DEVIATION, eng.MISSING, eng.OUT_OF_ORDER)]
    query = sess.symptom + " " + " ".join(r.sop_action for r in problems[:5])
    guide = []
    try:
        qv = await llm.embed_one(query, "RETRIEVAL_QUERY")
        guide = await retriever.retrieve(session, qv, query, k=5, doc_types=("troubleshooting_guide",),
                                         equipment=doc.equipment or None)
        if not guide and doc.equipment:
            guide = await retriever.retrieve(session, qv, query, k=5, doc_types=("troubleshooting_guide",))
    except llm.LLMError:
        guide = []
    table = "\n".join(f"Step {r.step_no}: {r.status} | SOP: {r.sop_requirement or r.sop_action} | "
                      f"done: {r.narrated or '-'} | critical={r.is_critical}" for r in rows if r.step_no)
    prompt = (f"SOP: {doc.doc_code} v{doc.version} ({doc.title})\nSymptom: {sess.symptom}\n\nComparison:\n{table}\n\n"
              f"Troubleshooting guide context:\n{build_context(guide) if guide else '(none available)'}")
    try:
        diag = await llm.generate_structured(prompt, Diagnosis, system=DIAGNOSE_PROMPT, tier="reasoning",
                                             mock=_mock_diagnosis(rows, len(guide)))
    except llm.LLMError as e:
        raise HTTPException(503, "The AI is busy - please try again in a moment." if e.busy else str(e))
    if any(r.is_critical and r.status in (eng.DEVIATION, eng.MISSING) for r in rows) and not diag.deviation_advice:
        diag.deviation_advice = ("A critical step deviated or was missed. Record this in line with the lab's "
                                 "deviation process before repeating the work.")
    # optional inventory check: any lot number mentioned in the conversation
    said = " ".join(m["content"] for m in (sess.conversation or []))
    warnings = []
    lots = (await session.execute(text("SELECT l.lot_no, r.name, l.expiry_date, l.quantity_available FROM reagent_lots l "
                                       "JOIN reagents r ON r.id=l.reagent_id"))).all()
    for lot_no, name, exp, qty in lots:
        if lot_no and re.search(rf"\b{re.escape(lot_no)}\b", said, re.I):
            if exp and exp <= date.today():
                warnings.append(f"Lot {lot_no} ({name}) is EXPIRED ({exp.isoformat()}).")
            elif exp and (exp - date.today()).days <= 30:
                warnings.append(f"Lot {lot_no} ({name}) expires soon ({exp.isoformat()}).")
    citations = [rag._citation(i, c) for i, c in enumerate(guide, start=1)]
    sess.diagnosis = {"diagnosis": diag.model_dump(), "warnings": warnings, "citations": citations}
    await audit.log(session, user, "troubleshoot_diagnosis", f"{doc.doc_code} v{doc.version}",
                    {"session_id": str(sess.id), "causes": len(diag.causes)}, audit.client_ip(request))
    await session.commit()
    return {"session_id": str(sess.id), "document": _doc_json(doc), "diagnosis": diag.model_dump(),
            "warnings": warnings, "citations": citations, "comparison": _rows_json(rows)}


@router.get("/{session_id}")
async def get_session_detail(session_id: uuid.UUID, user: User = require("knowledge.use"),
                             session: AsyncSession = Depends(get_session)):
    sess = await _own(session, session_id, user)
    doc = await session.get(Document, sess.document_id)
    return {"session_id": str(sess.id), "document": _doc_json(doc), "symptom": sess.symptom,
            "narrated": sess.narrated_steps, "comparison": sess.comparison, "questions": sess.questions_asked,
            "conversation": sess.conversation, "diagnosis": sess.diagnosis}
