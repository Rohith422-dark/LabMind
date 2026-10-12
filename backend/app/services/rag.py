"""Streaming RAG: intent -> cache -> retrieve -> gate 1 (cosine) -> gate 2 (ANSWERABLE line) -> stream -> citations."""
import logging
import re
import uuid
from collections.abc import AsyncIterator

from sqlalchemy import select

from app.config import get_settings
from app.db import session_maker
from app.models.tables import ChatHistory, KnowledgeGap, User
from app.prompts.system_prompt import SYSTEM_PROMPT, build_context
from app.services import answer_cache, audit, intent, inventory, llm, retriever

log = logging.getLogger("sla.rag")
MARK = re.compile(r"\[(\d{1,2})\]")
ANSWERABLE = re.compile(r"^\s*ANSWERABLE:\s*(yes|no)\s*$", re.I)
BUSY_MSG = "The AI is busy - please try again in a moment."


async def record_gap(user: User, question: str) -> uuid.UUID:
    norm = answer_cache.normalize(question)
    async with session_maker()() as s:
        gap = (await s.execute(select(KnowledgeGap).where(
            KnowledgeGap.normalized_question == norm, KnowledgeGap.status != "resolved")
            .order_by(KnowledgeGap.created_at))).scalars().first()
        if gap:
            gap.similar_count += 1
        else:
            gap = KnowledgeGap(question=question, normalized_question=norm, requested_by=user.id)
            s.add(gap)
        await s.flush()
        gid = gap.id
        await audit.log(s, user, "knowledge_gap_logged", question[:200], {"gap_id": str(gid)})
        await s.commit()
        return gid


def _citation(n: int, c: dict) -> dict:
    snippet = c["text"][:320].strip()
    return {"n": n, "document_id": str(c["document_id"]), "chunk_id": str(c["id"]), "doc_code": c["doc_code"],
            "title": c["title"], "version": c["version"], "page": c["page"], "section": c["section"],
            "snippet": snippet, "score": round(float(c.get("cosine", 0.0)), 3)}


def _mock_answer(chunks: list[dict], min_score: float, question: str = "") -> str:
    """DEV-ONLY stand-in for the LLM's gate 2: answerable if the top chunks cover most of the question's words."""
    from app.services.troubleshoot_engine import _tokens
    top = chunks[0]
    q = _tokens(question)
    have = _tokens(" ".join(c["text"] for c in chunks[:2]))
    if top["cosine"] < min_score or (q and len(q & have) / len(q) < 0.5):
        return "ANSWERABLE: no"
    sentences = re.split(r"(?<=[.!?])\s+", top["text"])
    return "ANSWERABLE: yes\n" + " ".join(sentences[:3]) + " [1]"


async def _inventory_answer(question: str) -> tuple[str, list[dict]]:
    async with session_maker()() as s:
        ids = await inventory.find_reagent_ids(s, question)
        lots = await inventory.lots_for(s, ids)
    if not ids:
        return ("I could not match a reagent from the inventory register in your question. "
                "Try the reagent name or CAS number, or open the Inventory page."), []
    if not lots:
        return "That reagent is in the register but no lots are recorded.", []
    ok = [l for l in lots if l["status"] != "red"]
    names = ", ".join(sorted({l["name"] for l in lots}))
    msg = (f"{names}: {len(lots)} lot(s) on record, {len(ok)} in date and in stock. "
           "Earliest-expiry usable lot first in the table below.")
    return msg, [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in l.items()
                  if k not in ("hazard_statements",)} for l in lots]


async def answer_stream(user: User, question: str, history: list[dict], ip: str | None,
                        use_cache: bool = True) -> AsyncIterator[dict]:
    s = get_settings()
    history = history[-6:]
    standalone_q = intent.standalone(question, history)
    kind = intent.classify(question)

    async with session_maker()() as db:
        chat = ChatHistory(user_id=user.id, question=question, source_type="internal", sources=[])
        db.add(chat)
        await db.flush()
        chat_id = chat.id
        await audit.log(db, user, "chat_question", question[:300], {"intent": kind}, ip)
        await db.commit()
    yield {"type": "meta", "chat_id": str(chat_id), "intent": kind}

    async def finish(answer: str, citations: list[dict], source_type="internal"):
        async with session_maker()() as db:
            row = await db.get(ChatHistory, chat_id)
            row.answer, row.sources, row.source_type = answer, citations, source_type
            await db.commit()

    if kind == "inventory":
        msg, lots = await _inventory_answer(question)
        for piece in re.findall(r"\S+\s*", msg):
            yield {"type": "token", "text": piece}
        if lots:
            yield {"type": "inventory", "lots": lots}
        await finish(msg, [])
        yield {"type": "done"}
        return

    # ---- cache (also what keeps rehearsed questions working offline)
    hit = None
    if use_cache:
        async with session_maker()() as db:
            hit = await answer_cache.get(db, standalone_q)
    if hit:
        for piece in re.findall(r"\S+\s*", hit["answer"]):
            yield {"type": "token", "text": piece}
        yield {"type": "citations", "citations": hit["sources"]}
        async with session_maker()() as db:
            note = await inventory.hazard_note(db, [standalone_q, hit["answer"]])
        if note:
            yield {"type": "safety", "note": note}
        await finish(hit["answer"], hit["sources"])
        yield {"type": "done"}
        return

    # ---- retrieve
    try:
        qvec = await llm.embed_one(standalone_q, "RETRIEVAL_QUERY")
    except llm.LLMError as e:
        yield {"type": "error", "message": BUSY_MSG if e.busy else str(e)}
        return
    async with session_maker()() as db:
        chunks = await retriever.retrieve(db, qvec, standalone_q, k=6)

    async def no_match():
        gid = await record_gap(user, question)
        await finish("", [])
        yield_ev = {"type": "no_match", "gap_id": str(gid)}
        return yield_ev

    # gate 1 (cheap)
    if not chunks or max(c["cosine"] for c in chunks) < s.vector_min_score:
        yield await no_match()
        yield {"type": "done"}
        return

    # gate 2 (LLM): first line must be ANSWERABLE
    prompt = f"Context:\n{build_context(chunks)}\n\nQuestion: {standalone_q}"
    buf, answer_parts, decided = "", [], False
    try:
        async for piece in llm.stream(prompt, system=SYSTEM_PROMPT, tier="fast",
                                      mock=lambda: _mock_answer(chunks, s.vector_min_score, standalone_q)):
            if decided:
                answer_parts.append(piece)
                yield {"type": "token", "text": piece}
                continue
            buf += piece
            if "\n" in buf:
                first, rest = buf.split("\n", 1)
                m = ANSWERABLE.match(first)
                decided = True
                if m and m.group(1).lower() == "no":
                    yield await no_match()
                    yield {"type": "done"}
                    return
                if not m:  # model ignored the format: treat the whole thing as the answer
                    rest = buf
                if rest:
                    answer_parts.append(rest)
                    yield {"type": "token", "text": rest}
        if not decided:  # single-line output
            m = ANSWERABLE.match(buf.strip())
            if m and m.group(1).lower() == "no" or not buf.strip():
                yield await no_match()
                yield {"type": "done"}
                return
            if buf.strip().lower().startswith("answerable: yes"):
                buf = ""
            answer_parts.append(buf)
            if buf:
                yield {"type": "token", "text": buf}
    except llm.LLMError as e:
        yield {"type": "error", "message": BUSY_MSG if e.busy else str(e)}
        return

    answer = "".join(answer_parts).strip()
    cited = sorted({int(n) for n in MARK.findall(answer) if 1 <= int(n) <= len(chunks)})
    citations = [_citation(n, chunks[n - 1]) for n in cited]
    yield {"type": "citations", "citations": citations}
    async with session_maker()() as db:
        note = await inventory.hazard_note(db, [standalone_q, answer] + [c["text"] for c in (chunks[n - 1] for n in cited)])
        if citations:
            await answer_cache.put(db, standalone_q, answer, citations)
            await db.commit()
    if note:
        yield {"type": "safety", "note": note}
    await finish(answer, citations)
    yield {"type": "done"}
