import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import require
from app.models.tables import Document, KnowledgeGap, User
from app.services import audit
from app.services.notify import notify

router = APIRouter(prefix="/gaps", tags=["gaps"])


class GapOut(BaseModel):
    id: uuid.UUID
    question: str
    status: str
    similar_count: int
    requested_by: uuid.UUID
    requester_name: str | None = None
    linked_document_id: uuid.UUID | None = None
    created_at: datetime


class LinkIn(BaseModel):
    document_id: uuid.UUID


@router.get("", response_model=list[GapOut])
async def list_gaps(user: User = require("gaps.view"), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(KnowledgeGap, User.full_name).join(User, User.id == KnowledgeGap.requested_by)
        .order_by(KnowledgeGap.similar_count.desc(), KnowledgeGap.created_at.desc()))).all()
    return [GapOut(id=g.id, question=g.question, status=g.status, similar_count=g.similar_count,
                   requested_by=g.requested_by, requester_name=name, linked_document_id=g.linked_document_id,
                   created_at=g.created_at) for g, name in rows]


@router.patch("/{gap_id}/request-sop", response_model=GapOut)
async def request_sop(request: Request, gap_id: uuid.UUID, user: User = require("gaps.request_sop"),
                      session: AsyncSession = Depends(get_session)):
    gap = await session.get(KnowledgeGap, gap_id)
    if gap is None:
        raise HTTPException(404, "Gap not found")
    if gap.status == "open":
        gap.status = "sop_requested"
    seniors = (await session.execute(select(User).where(User.role == "senior_analyst"))).scalars().all()
    for s in seniors:
        await notify(session, s.id, f"{user.full_name} requested an official SOP: {gap.question[:120]}", "/gaps")
    await audit.log(session, user, "sop_requested", gap.question[:200], {"gap_id": str(gap.id)}, audit.client_ip(request))
    await session.commit()
    return GapOut(id=gap.id, question=gap.question, status=gap.status, similar_count=gap.similar_count,
                  requested_by=gap.requested_by, linked_document_id=gap.linked_document_id, created_at=gap.created_at)


@router.patch("/{gap_id}/link", response_model=GapOut)
async def link_gap(request: Request, gap_id: uuid.UUID, body: LinkIn, user: User = require("gaps.link"),
                   session: AsyncSession = Depends(get_session)):
    gap = await session.get(KnowledgeGap, gap_id)
    doc = await session.get(Document, body.document_id)
    if gap is None or doc is None:
        raise HTTPException(404, "Gap or document not found")
    gap.linked_document_id, gap.status = doc.id, "resolved"
    await notify(session, gap.requested_by, f"Your question now has an official document: {doc.doc_code} v{doc.version}",
                 f"/sops/{doc.id}")
    await audit.log(session, user, "gap_linked", gap.question[:200], {"document": f"{doc.doc_code} v{doc.version}"},
                    audit.client_ip(request))
    await session.commit()
    return GapOut(id=gap.id, question=gap.question, status=gap.status, similar_count=gap.similar_count,
                  requested_by=gap.requested_by, linked_document_id=gap.linked_document_id, created_at=gap.created_at)
