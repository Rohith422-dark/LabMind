"""Project assistant (evidence-grounded chat), the external-search consent step, and the memory controls.

The project is authorised BEFORE the pipeline starts (`project_access`), and the pipeline filters retrieval by that project
id in SQL. The external-search endpoint can only act on a message that belongs to the caller AND to the project in the URL
and that is actually waiting for a decision - it cannot be used to trigger a search on its own.
"""
import json
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session, session_maker
from app.deps import require
from app.limiter import limiter
from app.models.tables import ChatHistory, Conversation, Experiment, Memory, ProjectDocument, User
from app.services import audit, project_rag
from app.services.access import ProjectCtx, project_access

router = APIRouter(prefix="/projects/{project_id}", tags=["project assistant"])
user_router = APIRouter(prefix="/memory", tags=["memory"])


class ProjectStreamIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    conversation_id: uuid.UUID | None = None


class ExternalDecisionIn(BaseModel):
    decision: Literal["allow_once", "allow_conversation", "deny"]


@router.post("/chat/stream")
@limiter.limit("30/minute")
async def stream(request: Request, body: ProjectStreamIn, ctx: ProjectCtx = project_access("viewer")):
    ip = audit.client_ip(request)
    user, project, role = ctx.user, ctx.project, ctx.role

    async def gen():
        try:
            async for ev in project_rag.answer_stream(user, project, body.question.strip(), body.conversation_id, ip, role):
                yield json.dumps(ev, default=str) + "\n"
        except Exception:  # noqa: BLE001  never leak a stack trace
            project_rag.log.exception("project chat failed")
            yield json.dumps({"type": "error", "message": "Something went wrong. Please try again."}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/chat/{chat_id}/external")
@limiter.limit("10/minute")
async def external_decision(request: Request, chat_id: uuid.UUID, body: ExternalDecisionIn,
                            ctx: ProjectCtx = project_access("viewer"), session: AsyncSession = Depends(get_session)):
    row = (await session.execute(select(ChatHistory).where(
        ChatHistory.id == chat_id, ChatHistory.user_id == ctx.user.id, ChatHistory.project_id == ctx.project.id)
        .with_for_update())).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Message not found")
    conv = await session.get(Conversation, row.conversation_id)
    if not (row.meta or {}).get("awaiting_external"):
        raise HTTPException(409, "No external-search decision is pending for this message")
    ip = audit.client_ip(request)
    if body.decision == "deny":
        row.meta = {**row.meta, "awaiting_external": False, "external_decision": "denied"}
        await audit.log(session, ctx.user, "project_external_denied", str(ctx.project.id), {"chat_id": str(chat_id)}, ip)
        await session.commit()
        return {"decision": "deny", "message": "Understood - I'll stay with the project information only. No external search was made."}
    result = None
    async for ev in project_rag.run_external(ctx.user, ctx.project.id, row.conversation_id, row.id, row.question, ip):
        result = ev
    if result is None or result["type"] != "external":
        raise HTTPException(503, (result or {}).get("message", "External search failed"))
    # re-read: run_external used its own session
    await session.refresh(row)
    row.meta = {**row.meta, "awaiting_external": False,
                "external_decision": "allowed_once" if body.decision == "allow_once" else "allowed_for_conversation"}
    if body.decision == "allow_conversation" and conv:
        conv.external_allowed = True
    await session.commit()
    return {"decision": body.decision, "external": {k: result[k] for k in ("chat_id", "answer", "sources", "grounded")}}


# ------------------------------------------------------------------ memory: project scope
class MemoryIn(BaseModel):
    content: str = Field(min_length=2, max_length=1000)
    kind: Literal["terminology", "finding", "note"] = "note"
    origin: Literal["user", "ai_suggested"] = "user"
    source_refs: list[dict] = Field(default_factory=list, max_length=10)


class MemoryPatch(BaseModel):
    content: str | None = Field(default=None, min_length=2, max_length=1000)
    kind: Literal["terminology", "finding", "note"] | None = None


class MemoryOut(BaseModel):
    id: uuid.UUID
    scope: str
    kind: str
    content: str
    origin: str
    stale: bool
    source_refs: list
    author_id: uuid.UUID
    author_name: str | None = None
    created_at: datetime
    updated_at: datetime
    verified: bool = False       # always False: memory is never a verified experimental record


async def _mem_out(session: AsyncSession, rows: list[Memory]) -> list[MemoryOut]:
    names = dict((await session.execute(select(User.id, User.full_name).where(User.id.in_({m.user_id for m in rows})))).all()) if rows else {}
    return [MemoryOut(id=m.id, scope=m.scope, kind=m.kind, content=m.content, origin=m.origin, stale=m.stale,
                      source_refs=m.source_refs or [], author_id=m.user_id, author_name=names.get(m.user_id),
                      created_at=m.created_at, updated_at=m.updated_at) for m in rows]


async def _check_refs(session: AsyncSession, project_id: uuid.UUID, refs: list[dict]) -> list[dict]:
    clean = []
    for r in refs:
        t, i = r.get("type"), r.get("id")
        try:
            uid = uuid.UUID(str(i))
        except ValueError:
            raise HTTPException(422, "Invalid source reference")
        model = {"experiment": Experiment, "document": ProjectDocument}.get(t)
        if model is None or (await session.execute(select(model.id).where(model.id == uid, model.project_id == project_id))).first() is None:
            raise HTTPException(422, "A source reference does not belong to this project")
        clean.append({"type": t, "id": str(uid), "version": r.get("version")})
    return clean


@router.get("/memory", response_model=list[MemoryOut])
async def list_project_memory(ctx: ProjectCtx = project_access("viewer"), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Memory).where(Memory.scope == "project", Memory.project_id == ctx.project.id)
                                  .order_by(Memory.created_at.desc()))).scalars().all()
    return await _mem_out(session, list(rows))


@router.post("/memory", response_model=MemoryOut, status_code=201)
async def add_project_memory(request: Request, body: MemoryIn, ctx: ProjectCtx = project_access("editor"),
                             session: AsyncSession = Depends(get_session)):
    refs = await _check_refs(session, ctx.project.id, body.source_refs)
    m = Memory(scope="project", project_id=ctx.project.id, user_id=ctx.user.id, kind=body.kind, content=body.content.strip(),
               origin=body.origin, source_refs=refs)
    session.add(m)
    await session.flush()
    await audit.log(session, ctx.user, "memory_added", str(ctx.project.id), {"scope": "project", "origin": body.origin}, audit.client_ip(request))
    await session.commit()
    return (await _mem_out(session, [m]))[0]


async def _own_or_owner(session: AsyncSession, ctx: ProjectCtx, memory_id: uuid.UUID) -> Memory:
    m = (await session.execute(select(Memory).where(Memory.id == memory_id, Memory.scope == "project",
                                                    Memory.project_id == ctx.project.id))).scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "Memory not found")
    if not ctx.is_owner and not (ctx.can("editor") and m.user_id == ctx.user.id):
        raise HTTPException(403, "Only the owner or the author can change this memory")
    return m


@router.patch("/memory/{memory_id}", response_model=MemoryOut)
async def edit_project_memory(memory_id: uuid.UUID, body: MemoryPatch, ctx: ProjectCtx = project_access("editor"),
                              session: AsyncSession = Depends(get_session)):
    m = await _own_or_owner(session, ctx, memory_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(m, k, v.strip() if k == "content" else v)
    m.stale = False                       # a human re-wrote it: they vouch it is current
    await session.commit()
    await session.refresh(m)
    return (await _mem_out(session, [m]))[0]


@router.post("/memory/{memory_id}/confirm", response_model=MemoryOut)
async def confirm_project_memory(memory_id: uuid.UUID, ctx: ProjectCtx = project_access("editor"),
                                 session: AsyncSession = Depends(get_session)):
    """Mark a stale memory as still valid after checking the changed source."""
    m = await _own_or_owner(session, ctx, memory_id)
    m.stale = False
    await session.commit()
    return (await _mem_out(session, [m]))[0]


@router.delete("/memory/{memory_id}", status_code=204)
async def delete_project_memory(request: Request, memory_id: uuid.UUID, ctx: ProjectCtx = project_access("editor"),
                                session: AsyncSession = Depends(get_session)):
    m = await _own_or_owner(session, ctx, memory_id)
    await session.delete(m)
    await audit.log(session, ctx.user, "memory_deleted", str(ctx.project.id), {"scope": "project"}, audit.client_ip(request))
    await session.commit()


# ------------------------------------------------------------------ memory: personal preferences
class UserMemoryIn(BaseModel):
    content: str = Field(min_length=2, max_length=1000)


@user_router.get("", response_model=list[MemoryOut])
async def list_user_memory(user: User = require("self.view"), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Memory).where(Memory.scope == "user", Memory.user_id == user.id)
                                  .order_by(Memory.created_at.desc()))).scalars().all()
    return await _mem_out(session, list(rows))


@user_router.post("", response_model=MemoryOut, status_code=201)
async def add_user_memory(body: UserMemoryIn, user: User = require("self.view"), session: AsyncSession = Depends(get_session)):
    m = Memory(scope="user", user_id=user.id, kind="preference", content=body.content.strip(), origin="user")
    session.add(m)
    await session.commit()
    return (await _mem_out(session, [m]))[0]


async def _mine(session: AsyncSession, user: User, memory_id: uuid.UUID) -> Memory:
    m = (await session.execute(select(Memory).where(Memory.id == memory_id, Memory.scope == "user", Memory.user_id == user.id))).scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "Memory not found")
    return m


@user_router.patch("/{memory_id}", response_model=MemoryOut)
async def edit_user_memory(memory_id: uuid.UUID, body: UserMemoryIn, user: User = require("self.view"),
                           session: AsyncSession = Depends(get_session)):
    m = await _mine(session, user, memory_id)
    m.content = body.content.strip()
    await session.commit()
    await session.refresh(m)
    return (await _mem_out(session, [m]))[0]


@user_router.delete("/{memory_id}", status_code=204)
async def delete_user_memory(memory_id: uuid.UUID, user: User = require("self.view"), session: AsyncSession = Depends(get_session)):
    m = await _mine(session, user, memory_id)
    await session.delete(m)
    await session.commit()
