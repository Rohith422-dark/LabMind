import asyncio
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import require
from app.models.tables import Chunk, Document, DocumentFile, IngestJob, SopStep, User
from app.schemas.documents import (
    DocumentDetail, DocumentOut, HighlightOut, JobCreated, JobOut, PublishIn, RetireIn, StepOutSchema,
)
from app.services import audit, ingest, parser
from app.services.parser import ParseError

router = APIRouter(prefix="/documents", tags=["documents"])
CHUNK_CHARS = 1500


@router.post("/extract", response_model=JobCreated, status_code=202)
async def extract(request: Request, file: UploadFile = File(...), user: User = require("sop.manage"),
                  session: AsyncSession = Depends(get_session)):
    data = await file.read(parser.MAX_BYTES + 1)
    try:
        job_id = await ingest.create_job(session, user, file.filename or "upload", data)
    except ParseError as e:
        raise HTTPException(422, str(e))
    await audit.log(session, user, "document_upload_started", file.filename, {"bytes": len(data)}, audit.client_ip(request))
    await session.commit()
    ingest.start(job_id)
    return JobCreated(job_id=job_id)


@router.get("/jobs/{job_id}", response_model=JobOut)
async def job_status(job_id: uuid.UUID, user: User = require("sop.manage"), session: AsyncSession = Depends(get_session)):
    job = await session.get(IngestJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


@router.post("/publish", response_model=DocumentOut)
async def publish(request: Request, body: PublishIn, user: User = require("sop.manage"),
                  session: AsyncSession = Depends(get_session)):
    job = await session.get(IngestJob, body.job_id)
    if job is None:
        raise HTTPException(404, "Upload not found")
    meta = body.model_dump(exclude={"job_id", "steps", "gap_id"})
    try:
        doc = await ingest.publish(session, user, job, meta, [s.model_dump() for s in body.steps], body.gap_id,
                                   audit.client_ip(request))
        await session.commit()
    except ingest.PublishError as e:
        await session.rollback()
        raise HTTPException(e.status, str(e))
    except ParseError as e:
        await session.rollback()
        raise HTTPException(422, str(e))
    return doc


@router.post("/{document_id}/retire", response_model=DocumentOut)
async def retire(request: Request, document_id: uuid.UUID, body: RetireIn, user: User = require("sop.manage"),
                 session: AsyncSession = Depends(get_session)):
    doc = await session.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "Document not found")
    try:
        await ingest.retire(session, user, doc, body.reason, audit.client_ip(request))
    except ingest.PublishError as e:
        raise HTTPException(e.status, str(e))
    await session.commit()
    return doc


def _filters(q, type_, department, equipment, status):
    stmt = select(Document).order_by(Document.doc_code, Document.version.desc())
    if type_:
        stmt = stmt.where(Document.doc_type == type_)
    if department:
        stmt = stmt.where(Document.department == department)
    if equipment:
        stmt = stmt.where(Document.equipment.ilike(f"%{equipment}%"))
    if status:
        stmt = stmt.where(Document.status == status)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Document.doc_code.ilike(like), Document.title.ilike(like), Document.equipment.ilike(like),
                              func.to_tsvector("english", func.coalesce(Document.full_text, ""))
                              .op("@@")(func.websearch_to_tsquery("english", q))))
    return stmt


@router.get("/search", response_model=list[DocumentOut])
@router.get("", response_model=list[DocumentOut])
async def list_documents(q: str | None = None, type: str | None = None, department: str | None = None,
                         equipment: str | None = None, status: str | None = None,
                         user: User = require("knowledge.use"), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(_filters(q, type, department, equipment, status).limit(300))).scalars().all()
    return rows


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(document_id: uuid.UUID, user: User = require("knowledge.use"),
                       session: AsyncSession = Depends(get_session)):
    doc = await session.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "Document not found")
    steps = (await session.execute(select(SopStep).where(SopStep.document_id == doc.id)
                                   .order_by(SopStep.step_no))).scalars().all()
    out = DocumentDetail.model_validate(doc)
    out.steps = [StepOutSchema.model_validate(s) for s in steps]
    if doc.file_type == "docx":
        chunks = (await session.execute(select(Chunk).where(Chunk.document_id == doc.id)
                                        .order_by(Chunk.seq))).scalars().all()
        out.text_sections = [{"section": c.section, "text": c.text, "chunk_id": str(c.id)} for c in chunks]
    return out


@router.get("/{document_id}/file")
async def get_file(document_id: uuid.UUID, download: bool = False, user: User = require("knowledge.use"),
                   session: AsyncSession = Depends(get_session)):
    f = await session.get(DocumentFile, document_id)
    if f is None:
        raise HTTPException(404, "File not found")
    disp = "attachment" if download else "inline"
    safe = f.filename.replace('"', "")
    return Response(f.bytes, media_type=f.mime, headers={"Content-Disposition": f'{disp}; filename="{safe}"'})


@router.get("/{document_id}/highlights", response_model=HighlightOut)
async def highlights(document_id: uuid.UUID, chunk_id: uuid.UUID, user: User = require("knowledge.use"),
                     session: AsyncSession = Depends(get_session)):
    chunk = await session.get(Chunk, chunk_id)
    if chunk is None or chunk.document_id != document_id:
        raise HTTPException(404, "Passage not found")
    doc = await session.get(Document, document_id)
    if doc.file_type != "pdf" or chunk.page is None:
        return HighlightOut(page=chunk.page or 1, page_width=0, page_height=0, rects=[], text=chunk.text,
                            section=chunk.section)
    f = await session.get(DocumentFile, document_id)
    h = await asyncio.to_thread(parser.find_highlights, f.bytes, chunk.page, chunk.text)
    return HighlightOut(**h, text=chunk.text, section=chunk.section)


@router.get("/{doc_code}/versions", response_model=list[DocumentOut])
async def versions(doc_code: str, user: User = require("knowledge.use"), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Document).where(Document.doc_code == doc_code)
                                  .order_by(Document.version.desc()))).scalars().all()
    if not rows:
        raise HTTPException(404, "Document not found")
    return rows
