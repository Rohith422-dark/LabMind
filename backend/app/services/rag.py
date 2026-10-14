"""Streaming RAG: intent -> cache -> retrieve -> gate 1 (cosine) -> gate 2 (ANSWERABLE line) -> stream -> citations."""
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator

from sqlalchemy import func, select

from app.config import get_settings
from app.db import session_maker
from app.models.tables import ChatHistory, Conversation, Experiment, KnowledgeGap, Memory, Project, ProjectMember, User
from app.prompts.system_prompt import SYSTEM_PROMPT, build_context
from app.services import answer_cache, audit, intent, inventory, llm, project_memory, retriever

log = logging.getLogger("sla.rag")
MARK = re.compile(r"\[(\d{1,2})\]")
ANSWERABLE = re.compile(r"^\s*ANSWERABLE:\s*(yes|no)\s*$", re.I)
BUSY_MSG = "The AI is busy - please try again in a moment."


GENERAL_SYSTEM = """You are a friendly, knowledgeable AI assistant for a scientific laboratory team, personalised to one user.
Answer from your own general knowledge. Be accurate and concise; say so when you are unsure; never invent citations, URLs or numbers.
You do NOT have access to this lab's SOPs, projects, experiment records or inventory in this answer, so never claim to; if the user needs
those, suggest they ask about them directly in this chat (the app will ask their permission before using project data). Never offer to browse drives, files or systems. For safety-critical details (doses, concentrations,
hazards) remind them to verify against the official SOP or SDS. Follow the user's saved preferences and use the conversation so far."""
PROJECT_RE = re.compile(r"\b(projects?|experiments?|experimental (?:records?|data)|(?:my|our) (?:data|results|runs|measurements|notebook))\b", re.I)


async def matching_projects(user: User, question: str) -> list[dict]:
    """The user's own projects, if the question looks like it is about projects/experiments (keyword, project name or experiment id)."""
    async with session_maker()() as db:
        rows = (await db.execute(select(Project.id, Project.name, ProjectMember.role).join(
            ProjectMember, ProjectMember.project_id == Project.id).where(ProjectMember.user_id == user.id,
                                                                         Project.archived_at.is_(None)))).all()
        if not rows:
            return []
        q = question.lower()
        hit = bool(PROJECT_RE.search(question)) or any(r.name.lower() in q for r in rows)
        if not hit:
            idents = (await db.execute(select(Experiment.identifier).where(
                Experiment.project_id.in_([r.id for r in rows]), Experiment.voided_at.is_(None)))).scalars().all()
            hit = any(re.search(rf"(?<![\w-]){re.escape(i)}(?![\w-])", question, re.I) for i in idents)
        return [{"id": str(r.id), "name": r.name, "role": r.role} for r in rows] if hit else []


REGISTER_SYSTEM = """You answer questions about this laboratory's reagents, chemicals and ingredients for a scientist.
You are given LIVE DATA from the lab's inventory register (reagents, lots, quantities, expiry, locations, hazards, suppliers).
Rules: for anything about THIS lab's stock (quantity, availability, lots, expiry, location, storage, supplier, hazards on record) use ONLY the register data
and quote its numbers exactly; if the register does not contain it, say so. Expired or quarantined stock is never usable. You may add short general
chemistry knowledge (what a substance is, typical composition of a standard buffer, why a hazard matters) but put it under a separate line starting with
"General knowledge:" and never present it as register data. For safety-critical handling remind the user to check the SDS. Be concise; use short lists."""


async def general_answer(user: User, conversation_id: uuid.UUID, question: str, system: str = GENERAL_SYSTEM,
                         context: str | None = None) -> AsyncIterator[str]:
    """Parametric-knowledge answer, personalised with saved preferences, recent turns, the rolling summary and recent topics."""
    async with session_maker()() as db:
        conv = await db.get(Conversation, conversation_id)
        summary, turns = await project_memory.conversation_context(db, conv)
        prefs = (await db.execute(select(Memory).where(Memory.scope == "user", Memory.user_id == user.id, Memory.stale.is_(False))
                                  .order_by(Memory.created_at.desc()).limit(8))).scalars().all()
        topics = (await db.execute(select(Conversation.title).where(Conversation.user_id == user.id, Conversation.id != conversation_id)
                                   .order_by(Conversation.updated_at.desc()).limit(5))).scalars().all()
    parts = [f"The user is {user.full_name} ({user.role.replace('_', ' ')})."]
    if prefs:
        parts.append("Saved preferences:\n" + "\n".join(f"- {m.content}" for m in prefs))
    if topics:
        parts.append("Topics of their recent other conversations: " + "; ".join(t[:80] for t in topics))
    if summary:
        parts.append("Summary of earlier turns of this conversation (unverified): " + summary)
    if turns:
        parts.append("Recent turns:\n" + "\n".join(f"{t['role']}: {t['content']}" for t in turns))
    if context:
        parts.append("Inventory register data (live):\n" + context)
    prompt = "\n\n".join(parts) + f"\n\nQuestion: {question}"
    async for piece in llm.stream(prompt, system=system, tier="fast",
                                  mock="(Mock AI, development only) " + ("Register data received:\n" + context[:700] if context else "This is a placeholder general answer, not real guidance.")):
        yield piece


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
    return msg, json.loads(json.dumps([{k: v for k, v in l.items() if k != "hazard_statements"} for l in lots], default=str))


async def load_history(user_id: uuid.UUID, conversation_id: uuid.UUID, limit: int = 6) -> list[dict]:
    """Server-side memory: the last turns of a saved conversation (oldest first), as chat-style messages."""
    async with session_maker()() as db:
        rows = (await db.execute(
            select(ChatHistory).where(ChatHistory.user_id == user_id, ChatHistory.conversation_id == conversation_id,
                                      ChatHistory.source_type == "internal", ChatHistory.answer.is_not(None))
            .order_by(ChatHistory.created_at.desc()).limit(limit // 2 or 1))).scalars().all()
    out: list[dict] = []
    for r in reversed(rows):
        out += [{"role": "user", "content": r.question}, {"role": "assistant", "content": (r.answer or "")[:800]}]
    return out


async def answer_stream(user: User, question: str, history: list[dict], ip: str | None,
                        use_cache: bool = True, conversation_id: uuid.UUID | None = None,
                        mode: str = "strict", project_check: bool = True) -> AsyncIterator[dict]:
    s = get_settings()
    if conversation_id:  # persistent memory beats whatever the client sent
        history = await load_history(user.id, conversation_id) or history
    else:
        conversation_id = uuid.uuid4()
    history = history[-6:]
    standalone_q = intent.standalone(question, history)
    kind = intent.classify(question)
    extra: dict = {}  # safety note / inventory lots / gap id: persisted so a reloaded chat looks the same

    async with session_maker()() as db:
        conv = await db.get(Conversation, conversation_id)
        if conv is None:
            db.add(Conversation(id=conversation_id, user_id=user.id, title=question[:120]))
        elif conv.user_id != user.id or conv.project_id is not None:
            yield {"type": "error", "message": "Conversation not found"}
            return
        else:
            conv.updated_at = func.now()
        chat = ChatHistory(user_id=user.id, question=question, source_type="internal", sources=[],
                           conversation_id=conversation_id)
        db.add(chat)
        await db.flush()
        chat_id = chat.id
        await audit.log(db, user, "chat_question", question[:300], {"intent": kind}, ip)
        await db.commit()
    yield {"type": "meta", "chat_id": str(chat_id), "intent": kind, "conversation_id": str(conversation_id)}

    async def finish(answer: str, citations: list[dict], source_type="internal"):
        async with session_maker()() as db:
            row = await db.get(ChatHistory, chat_id)
            row.answer, row.sources, row.source_type, row.meta = answer, citations, source_type, extra
            await db.commit()

    assistant = mode == "assistant"

    async def general_events(system: str = GENERAL_SYSTEM, context: str | None = None, flag: str = "general"):
        """assistant mode: answer from the model's own knowledge (or the live register), clearly labelled, and remember the turn."""
        parts: list[str] = []
        try:
            async for piece in general_answer(user, conversation_id, question, system, context):
                parts.append(piece)
                yield {"type": "token", "text": piece}
        except llm.LLMError as e:
            yield {"type": "error", "message": BUSY_MSG if e.busy else str(e)}
            return
        extra[flag] = True
        await finish("".join(parts).strip(), [])
        async with session_maker()() as db:
            conv = await db.get(Conversation, conversation_id)
            await project_memory.refresh_summary(db, conv)
            await db.commit()
        yield {"type": flag}
        yield {"type": "done"}

    if assistant:
        remembered = project_memory.parse_remember(question)
        if remembered:   # "Remember that I prefer ..." -> a private, editable preference
            async with session_maker()() as db:
                db.add(Memory(scope="user", kind="preference", user_id=user.id, content=remembered[:1000], origin="user", source_refs=[]))
                await audit.log(db, user, "memory_added", None, {"scope": "user", "via": "assistant"}, ip)
                await db.commit()
            msg = f'Saved to your personal preferences: "{remembered}". I will use it in future conversations.'
            for piece in re.findall(r"\S+\s*", msg):
                yield {"type": "token", "text": piece}
            extra["command"] = "remember"
            await finish(msg, [])
            yield {"type": "done"}
            return
        projs = await matching_projects(user, question) if project_check else []
        if projs:        # project / experiment data is private: ask before looking
            msg = ("This looks like a question about your projects or experiments. May I look at your project data to answer it? "
                   "Choose a project, or answer in general terms instead.")
            extra.update(awaiting_project=True, projects=projs)
            for piece in re.findall(r"\S+\s*", msg):
                yield {"type": "token", "text": piece}
            await finish(msg, [])
            yield {"type": "need_project", "chat_id": str(chat_id), "projects": projs}
            yield {"type": "done"}
            return

    if assistant:    # reagent / stock / ingredient questions: answer from the LIVE inventory register
        async with session_maker()() as db:
            reg = await inventory.register_context(db, standalone_q)
        if reg:
            if reg["lots"]:
                lots = json.loads(json.dumps(reg["lots"], default=str))      # UUIDs/dates -> JSON-safe for the stored message
                extra["lots"] = lots
                yield {"type": "inventory", "lots": lots}
            async for e in general_events(REGISTER_SYSTEM, reg["text"], "register"):
                yield e
            return

    if kind == "inventory":
        msg, lots = await _inventory_answer(question)
        for piece in re.findall(r"\S+\s*", msg):
            yield {"type": "token", "text": piece}
        if lots:
            extra["lots"] = lots
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
            extra["safety"] = note
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
        extra["gap_id"] = str(gid)
        await finish("", [])
        yield_ev = {"type": "no_match", "gap_id": str(gid)}
        return yield_ev

    # gate 1 (cheap)
    if not chunks or max(c["cosine"] for c in chunks) < s.vector_min_score:
        if assistant:
            async for e in general_events():
                yield e
            return
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
                    if assistant:
                        async for e in general_events():
                            yield e
                        return
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
        extra["safety"] = note
        yield {"type": "safety", "note": note}
    await finish(answer, citations)
    yield {"type": "done"}
