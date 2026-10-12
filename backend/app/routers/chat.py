import json
import uuid
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import require
from app.limiter import limiter
from app.models.tables import ChatHistory, KnowledgeGap, User
from app.prompts.gemini_prompt import EXTERNAL_PROMPT
from app.services import audit, llm, rag
from app.services.sanitizer import sanitize

router = APIRouter(prefix="/chat", tags=["chat"])


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class StreamIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    history: list[Turn] = []


class ExternalIn(BaseModel):
    gap_id: uuid.UUID


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
    created_at: datetime
    model_config = {"from_attributes": True}


@router.post("/stream")
@limiter.limit("30/minute")
async def stream(request: Request, body: StreamIn, user: User = require("knowledge.use")):
    ip = audit.client_ip(request)

    async def gen():
        try:
            async for ev in rag.answer_stream(user, body.question.strip(), [t.model_dump() for t in body.history], ip):
                yield json.dumps(ev, default=str) + "\n"
        except Exception:  # noqa: BLE001  never leak a stack trace to the client
            rag.log.exception("stream failed")
            yield json.dumps({"type": "error", "message": "Something went wrong. Please try again."}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/external", response_model=ExternalOut)
@limiter.limit("10/minute")
async def external(request: Request, body: ExternalIn, user: User = require("external.optin"),
                   session: AsyncSession = Depends(get_session)):
    gap = await session.get(KnowledgeGap, body.gap_id)
    if gap is None:
        raise HTTPException(404, "Question not found")
    question = sanitize(gap.question)  # server-side stored text only; client text is never trusted
    try:
        res = await llm.generate_grounded(
            question, system=EXTERNAL_PROMPT, tier="fast",
            mock="(Mock AI, development only) This is a placeholder external answer. It is not real guidance.")
    except llm.LLMError as e:
        raise HTTPException(503, "The AI is busy - please try again in a moment." if e.busy else str(e))
    sources = [{"title": s.title, "uri": s.uri, "domain": urlparse(s.uri).netloc} for s in res.sources]
    chat = ChatHistory(user_id=user.id, question=gap.question, answer=res.text, source_type="external", sources=sources)
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
