import json
import uuid
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import require
from app.limiter import limiter
from app.models.tables import ChatHistory, Conversation, KnowledgeGap, Project, User
from app.prompts.gemini_prompt import EXTERNAL_PROMPT
from app.services import access, audit, llm, rag
from app.services.sanitizer import sanitize

router = APIRouter(prefix="/chat", tags=["chat"])


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class StreamIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    history: list[Turn] = []
    conversation_id: uuid.UUID | None = None   # continue a saved conversation (server-side memory)
    mode: Literal["strict", "assistant"] = "strict"   # assistant: general questions answered from model knowledge, project questions ask first
    project_check: bool = True                 # False once the user declined to share project data for this question


class ExternalIn(BaseModel):
    gap_id: uuid.UUID
    conversation_id: uuid.UUID | None = None


class WebSourceOut(BaseModel):
    title: str
    uri: str
    domain: str


class ExternalOut(BaseModel):
    chat_id: uuid.UUID
    answer: str
    sources: list[WebSourceOut]
    grounded: bool
    gap_id: uuid.UUID


class FeedbackIn(BaseModel):
    feedback: Literal["up", "down"]


class HistoryOut(BaseModel):
    id: uuid.UUID
    question: str
    answer: str | None
    source_type: str
    sources: list
    feedback: str | None
    conversation_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    meta: dict = {}
    created_at: datetime
    model_config = {"from_attributes": True}


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    last_at: datetime
    turns: int
    project_id: uuid.UUID | None = None
    project_name: str | None = None


class RenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ConversationMemoryOut(BaseModel):
    summary: str | None
    summary_stale: bool
    summarised_turns: int
    external_allowed: bool
    note: str = "AI-generated summary of earlier turns. It is context for the assistant, not a verified record."


@router.post("/stream")
@limiter.limit("30/minute")
async def stream(request: Request, body: StreamIn, user: User = require("knowledge.use")):
    ip = audit.client_ip(request)

    async def gen():
        try:
            async for ev in rag.answer_stream(user, body.question.strip(), [t.model_dump() for t in body.history], ip,
                                         conversation_id=body.conversation_id, mode=body.mode, project_check=body.project_check):
                yield json.dumps(ev, default=str) + "\n"
        except Exception:  # noqa: BLE001  never leak a stack trace to the client
            rag.log.exception("stream failed")
            yield json.dumps({"type": "error", "message": "Something went wrong. Please try again."}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


class ProjectAnswerIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    project_id: uuid.UUID
    conversation_id: uuid.UUID | None = None


@router.post("/assistant/project-answer")
@limiter.limit("30/minute")
async def assistant_project_answer(request: Request, body: ProjectAnswerIn, user: User = require("projects.use"),
                                   session: AsyncSession = Depends(get_session)):
    """The user said yes to 'may I look at your project data?': run the evidence-grounded project pipeline for the project
    they chose (membership checked here), inside their general conversation."""
    from app.services import project_rag
    ctx = await access.load_ctx(session, user, body.project_id, "viewer")
    ip, project, role = audit.client_ip(request), ctx.project, ctx.role

    async def gen():
        try:
            async for ev in project_rag.answer_stream(user, project, body.question.strip(), body.conversation_id, ip, role, global_conv=True):
                yield json.dumps(ev, default=str) + "\n"
        except Exception:  # noqa: BLE001
            rag.log.exception("assistant project answer failed")
            yield json.dumps({"type": "error", "message": "Something went wrong. Please try again."}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/external", response_model=ExternalOut)
@limiter.limit("10/minute")
async def external(request: Request, body: ExternalIn, user: User = require("external.optin"),
                   session: AsyncSession = Depends(get_session)):
    gap = await session.get(KnowledgeGap, body.gap_id)
    if gap is None:
        raise HTTPException(404, "Question not found")
    if body.conversation_id:
        conv = await session.get(Conversation, body.conversation_id)
        if conv is not None and (conv.user_id != user.id or conv.project_id is not None):
            raise HTTPException(404, "Conversation not found")
    question = sanitize(gap.question)  # server-side stored text only; client text is never trusted
    try:
        res = await llm.generate_grounded(
            question, system=EXTERNAL_PROMPT, tier="fast",
            mock="(Mock AI, development only) This is a placeholder external answer. It is not real guidance.")
    except llm.LLMError as e:
        raise HTTPException(503, "The AI is busy - please try again in a moment." if e.busy else str(e))
    sources = [{"title": s.title, "uri": s.uri, "domain": urlparse(s.uri).netloc} for s in res.sources]
    chat = ChatHistory(user_id=user.id, question=gap.question, answer=res.text, source_type="external", sources=sources,
                       conversation_id=body.conversation_id, meta={"gap_id": str(gap.id), "grounded": res.grounded})
    session.add(chat)
    await session.flush()
    await audit.log(session, user, "external_ai_used", gap.question[:200],
                    {"gap_id": str(gap.id), "grounded": res.grounded, "sent_to_ai": question,
                     "web_sources": len(sources)}, audit.client_ip(request))
    await session.commit()
    return ExternalOut(chat_id=chat.id, answer=res.text, sources=sources, grounded=res.grounded, gap_id=gap.id)


@router.patch("/{chat_id}/feedback", response_model=HistoryOut)
async def feedback(chat_id: uuid.UUID, body: FeedbackIn, user: User = require("knowledge.use"),
                   session: AsyncSession = Depends(get_session)):
    row = await session.get(ChatHistory, chat_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "Chat not found")
    row.feedback = body.feedback
    await session.commit()
    return row


@router.get("/history", response_model=list[HistoryOut])
async def history(limit: int = Query(50, ge=1, le=200), user: User = require("knowledge.use"),
                  session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(ChatHistory).where(ChatHistory.user_id == user.id)
                                  .order_by(ChatHistory.created_at.desc()).limit(limit))).scalars().all()
    return rows


async def _own_conversation(session: AsyncSession, user: User, conversation_id: uuid.UUID) -> Conversation:
    """Owner-only, and for a project conversation the owner must STILL be a member (revoked access hides it)."""
    conv = await session.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(404, "Conversation not found")
    if conv.project_id is not None and await access.role_of(session, user.id, conv.project_id) is None:
        raise HTTPException(404, "Conversation not found")
    return conv


@router.get("/conversations", response_model=list[ConversationOut])
async def conversations(limit: int = Query(30, ge=1, le=100), project_id: uuid.UUID | None = None,
                        scope: str = Query("all", pattern="^(all|global|project)$"), user: User = require("self.view"),
                        session: AsyncSession = Depends(get_session)):
    """Recent chats of the current user only (newest first). Conversations of projects the user no longer belongs to are hidden."""
    where = ["c.user_id = :u",
             "(c.project_id IS NULL OR EXISTS (SELECT 1 FROM project_members m WHERE m.project_id = c.project_id AND m.user_id = c.user_id))"]
    params: dict = {"u": user.id, "n": limit}
    if project_id:
        where.append("c.project_id = :pid")
        params["pid"] = project_id
    elif scope == "global":
        where.append("c.project_id IS NULL")
    elif scope == "project":
        where.append("c.project_id IS NOT NULL")
    rows = (await session.execute(text(
        "SELECT c.id, c.title, c.project_id, p.name AS project_name, c.updated_at AS last_at, "
        "(SELECT count(*) FROM chat_history h WHERE h.conversation_id = c.id AND h.user_id = c.user_id AND h.source_type = 'internal') AS turns "
        "FROM conversations c LEFT JOIN projects p ON p.id = c.project_id WHERE " + " AND ".join(where)
        + " ORDER BY c.updated_at DESC LIMIT :n"), params)).mappings().all()
    return [ConversationOut(**dict(r)) for r in rows]


@router.get("/conversations/{conversation_id}", response_model=list[HistoryOut])
async def conversation(conversation_id: uuid.UUID, user: User = require("self.view"),
                       session: AsyncSession = Depends(get_session)):
    await _own_conversation(session, user, conversation_id)
    rows = (await session.execute(select(ChatHistory).where(ChatHistory.user_id == user.id,
                                                             ChatHistory.conversation_id == conversation_id)
                                  .order_by(ChatHistory.created_at))).scalars().all()
    if not rows:
        raise HTTPException(404, "Conversation not found")
    return rows


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut)
async def rename_conversation(conversation_id: uuid.UUID, body: RenameIn, user: User = require("self.view"),
                              session: AsyncSession = Depends(get_session)):
    conv = await _own_conversation(session, user, conversation_id)
    conv.title = body.title.strip()
    await session.commit()
    pname = (await session.get(Project, conv.project_id)).name if conv.project_id else None
    turns = (await session.execute(text("SELECT count(*) FROM chat_history WHERE conversation_id=:c AND user_id=:u AND source_type='internal'"),
                                   {"c": conv.id, "u": user.id})).scalar_one()
    return ConversationOut(id=conv.id, title=conv.title, last_at=conv.updated_at, turns=turns, project_id=conv.project_id, project_name=pname)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(request: Request, conversation_id: uuid.UUID, user: User = require("self.view"),
                              session: AsyncSession = Depends(get_session)):
    """Permanent: messages, the summary and the external-allowed flag go with it."""
    conv = await _own_conversation(session, user, conversation_id)
    project_id = str(conv.project_id) if conv.project_id else None
    await session.execute(text("DELETE FROM chat_history WHERE conversation_id = :c AND user_id = :u"), {"c": conv.id, "u": user.id})
    await session.delete(conv)
    await audit.log(session, user, "conversation_deleted", str(conversation_id), {"project_id": project_id}, audit.client_ip(request))
    await session.commit()


@router.get("/conversations/{conversation_id}/memory", response_model=ConversationMemoryOut)
async def conversation_memory(conversation_id: uuid.UUID, user: User = require("self.view"),
                              session: AsyncSession = Depends(get_session)):
    conv = await _own_conversation(session, user, conversation_id)
    return ConversationMemoryOut(summary=conv.summary, summary_stale=conv.summary_stale, summarised_turns=conv.summary_through,
                                 external_allowed=conv.external_allowed)


@router.delete("/conversations/{conversation_id}/memory", status_code=204)
async def clear_conversation_memory(conversation_id: uuid.UUID, user: User = require("self.view"),
                                    session: AsyncSession = Depends(get_session)):
    """Forget the summary and withdraw 'allow external search for this conversation'."""
    conv = await _own_conversation(session, user, conversation_id)
    conv.summary, conv.summary_through, conv.summary_stale, conv.external_allowed = None, 0, False, False
    await session.commit()
