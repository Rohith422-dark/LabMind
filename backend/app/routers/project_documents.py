"""Project documentation: upload / replace / search / view / download / remove, kept in sync with the retrieval index.

Every handler loads the document THROUGH the project in the URL (`get_child`), so a document id from another project is a
404 even for a user who belongs to both. Files live on disk under a server-generated key; the database holds metadata,
extracted text (for viewing) and chunks+embeddings (for retrieval).
"""
import asyncio
import hashlib
import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.limiter import limiter
from app.models.tables import ProjectDocument, User
from app.services import audit, project_docs, project_index
from app.services.access import ProjectCtx, get_child, project_access
from app.services.parser import ParseError

log = logging.getLogger("sla.project_docs")
router = APIRouter(prefix="/projects/{project_id}/documents", tags=["project documents"])


class ProjectDocumentOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    lineage_id: uuid.UUID
    version: int
    title: str
    category: str | None = None
    filename: str
    file_type: str
    size_bytes: int
    status: str
    page_count: int | None = None
    char_count: int = 0
    chunks: int = 0
    warnings: list[str] = []
    uploaded_by: uuid.UUID
    uploaded_by_name: str | None = None
    created_at: datetime


class ProjectDocumentPage(BaseModel):
    items: list[ProjectDocumentOut]
    total: int
    limit: int
    offset: int


async def _out(session: AsyncSession, docs: list[ProjectDocument]) -> list[ProjectDocumentOut]:
    if not docs:
        return []
    names = dict((await session.execute(select(User.id, User.full_name).where(User.id.in_({d.uploaded_by for d in docs})))).all())
    counts = dict((await session.execute(text(
        "SELECT source_id, count(*) FROM project_chunks WHERE project_id = :p AND source_type = 'document' "
        "AND source_id = ANY(:ids) GROUP BY 1"), {"p": docs[0].project_id, "ids": [d.id for d in docs]})).all())
    return [ProjectDocumentOut(**{c: getattr(d, c) for c in ("id", "project_id", "lineage_id", "version", "title", "category", "filename",
                                                      "file_type", "size_bytes", "status", "page_count", "char_count", "warnings",
                                                      "uploaded_by", "created_at")},
                        chunks=counts.get(d.id, 0), uploaded_by_name=names.get(d.uploaded_by)) for d in docs]


async def _read_upload(file: UploadFile) -> bytes:
    limit = get_settings().project_max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File is larger than {get_settings().project_max_upload_mb} MB")
    return data


def _can_modify(ctx: ProjectCtx, doc: ProjectDocument) -> bool:
    return ctx.is_owner or (ctx.can("editor") and doc.uploaded_by == ctx.user.id)


async def _ingest(session: AsyncSession, ctx: ProjectCtx, file: UploadFile, title: str | None, category: str | None,
                  lineage_id: uuid.UUID | None = None, version: int = 1) -> ProjectDocument:
    filename = project_docs.clean_filename(file.filename or "document")
    data = await _read_upload(file)
    try:
        ex = await asyncio.to_thread(project_docs.extract, filename, data)
    except ParseError as e:
        raise HTTPException(422, str(e))
    except Exception:  # noqa: BLE001  a parser crash on hostile input must never become a 500 with a trace
        log.exception("document parse failed")
        raise HTTPException(422, "This file could not be read. It may be corrupt or in an unsupported format.")
    sha = hashlib.sha256(data).hexdigest()
    dup = (await session.execute(select(ProjectDocument).where(
        ProjectDocument.project_id == ctx.project.id, ProjectDocument.sha256 == sha, ProjectDocument.status == "ready"))).scalars().first()
    if dup:
        raise HTTPException(409, f"An identical file is already in this project as '{dup.title}'")
    key = project_docs.new_key()
    doc = ProjectDocument(
        project_id=ctx.project.id, lineage_id=lineage_id or uuid.uuid4(), version=version,
        title=(title or filename.rsplit(".", 1)[0]).strip()[:240] or filename, category=(category or None) and category.strip()[:80],
        filename=filename, file_type=ex.file_type, mime=project_docs.ALLOWED[ex.file_type], size_bytes=len(data), sha256=sha,
        storage_key=key, status="ready", page_count=ex.doc.page_count, char_count=len(ex.doc.full_text), warnings=ex.warnings,
        extracted=project_docs.pages_payload(ex.doc), uploaded_by=ctx.user.id)
    project_docs.save(ctx.project.id, key, data)
    try:
        session.add(doc)
        await session.flush()
        await project_index.index_document(session, doc, ex.doc)
    except Exception:
        project_docs.remove(ctx.project.id, key)
        raise
    return doc


@router.post("", response_model=ProjectDocumentOut, status_code=201)
@limiter.limit("30/minute")
async def upload_document(request: Request, file: UploadFile = File(...), title: str | None = Form(None, max_length=240),
                          category: str | None = Form(None, max_length=80), ctx: ProjectCtx = project_access("editor"),
                          session: AsyncSession = Depends(get_session)):
    doc = await _ingest(session, ctx, file, title, category)
    await audit.log(session, ctx.user, "project_document_uploaded", str(doc.id),
                    {"project_id": str(ctx.project.id), "type": doc.file_type, "bytes": doc.size_bytes}, audit.client_ip(request))
    await session.commit()
    return (await _out(session, [doc]))[0]


@router.get("", response_model=ProjectDocumentPage)
async def list_documents(q: str | None = Query(None, max_length=200), category: str | None = None, file_type: str | None = None,
                         include_history: bool = False, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
                         ctx: ProjectCtx = project_access("viewer"), session: AsyncSession = Depends(get_session)):
    """`q` matches titles/filenames and the extracted text of the project's own documents."""
    where = ["d.project_id = :pid", "d.status = 'ready'" if not include_history else "d.status <> 'deleted'"]
    params: dict[str, Any] = {"pid": ctx.project.id, "lim": limit, "off": offset}
    if q:
        where.append("(d.title ILIKE :ql OR d.filename ILIKE :ql OR d.id IN (SELECT source_id FROM project_chunks "
                     "WHERE project_id = :pid AND source_type = 'document' AND tsv @@ websearch_to_tsquery('english', :q)))")
        params.update(q=q, ql=f"%{q}%")
    if category:
        where.append("d.category = :cat")
        params["cat"] = category
    if file_type:
        where.append("d.file_type = :ft")
        params["ft"] = file_type
    w = " AND ".join(where)
    total = (await session.execute(text(f"SELECT count(*) FROM project_documents d WHERE {w}"), params)).scalar_one()
    ids = (await session.execute(text(f"SELECT d.id FROM project_documents d WHERE {w} ORDER BY d.created_at DESC LIMIT :lim OFFSET :off"),
                                 params)).scalars().all()
    rows = {d.id: d for d in (await session.execute(select(ProjectDocument).where(ProjectDocument.id.in_(ids)))).scalars()} if ids else {}
    return ProjectDocumentPage(items=await _out(session, [rows[i] for i in ids]), total=total, limit=limit, offset=offset)


@router.get("/{document_id}", response_model=ProjectDocumentOut)
async def get_document(document_id: uuid.UUID, ctx: ProjectCtx = project_access("viewer"), session: AsyncSession = Depends(get_session)):
    doc = await get_child(session, ProjectDocument, ctx.project.id, document_id, "Document")
    if doc.status == "deleted":
        raise HTTPException(404, "Document not found")
    return (await _out(session, [doc]))[0]


@router.get("/{document_id}/content")
async def get_content(document_id: uuid.UUID, ctx: ProjectCtx = project_access("viewer"), session: AsyncSession = Depends(get_session)):
    """Extracted text with page numbers (null for formats without pages) - what the index was built from."""
    doc = await get_child(session, ProjectDocument, ctx.project.id, document_id, "Document")
    if doc.status == "deleted":
        raise HTTPException(404, "Document not found")
    return {"id": str(doc.id), "title": doc.title, "version": doc.version, "status": doc.status, "warnings": doc.warnings,
            "pages": doc.extracted}


@router.get("/{document_id}/file")
async def download(document_id: uuid.UUID, ctx: ProjectCtx = project_access("viewer"), session: AsyncSession = Depends(get_session)):
    doc = await get_child(session, ProjectDocument, ctx.project.id, document_id, "Document")
    if doc.status == "deleted":
        raise HTTPException(404, "Document not found")
    try:
        data = project_docs.read(ctx.project.id, doc.storage_key)
    except FileNotFoundError:
        raise HTTPException(404, "The stored file is missing")
    safe = doc.filename.replace('"', "")
    return Response(data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{safe}"', "X-Content-Type-Options": "nosniff"})


@router.get("/{document_id}/versions", response_model=list[ProjectDocumentOut])
async def versions(document_id: uuid.UUID, ctx: ProjectCtx = project_access("viewer"), session: AsyncSession = Depends(get_session)):
    doc = await get_child(session, ProjectDocument, ctx.project.id, document_id, "Document")
    rows = (await session.execute(select(ProjectDocument).where(
        ProjectDocument.project_id == ctx.project.id, ProjectDocument.lineage_id == doc.lineage_id,
        ProjectDocument.status != "deleted").order_by(ProjectDocument.version.desc()))).scalars().all()
    return await _out(session, list(rows))


@router.post("/{document_id}/replace", response_model=ProjectDocumentOut, status_code=201)
@limiter.limit("30/minute")
async def replace_document(request: Request, document_id: uuid.UUID, file: UploadFile = File(...),
                           title: str | None = Form(None, max_length=240), ctx: ProjectCtx = project_access("editor"),
                           session: AsyncSession = Depends(get_session)):
    """Upload a new version. The old version stays downloadable as history but is removed from retrieval immediately."""
    old = (await session.execute(select(ProjectDocument).where(
        ProjectDocument.id == document_id, ProjectDocument.project_id == ctx.project.id).with_for_update())).scalar_one_or_none()
    if old is None or old.status != "ready":
        raise HTTPException(404, "Document not found")
    if not _can_modify(ctx, old):
        raise HTTPException(403, "Only the owner or the uploader can replace this document")
    latest = (await session.execute(select(func.max(ProjectDocument.version)).where(
        ProjectDocument.lineage_id == old.lineage_id))).scalar_one()
    new = await _ingest(session, ctx, file, title or old.title, old.category, old.lineage_id, latest + 1)
    old.status = "superseded"
    await project_index.drop_chunks(session, ctx.project.id, "document", old.id)
    await project_index.invalidate_derived(session, ctx.project.id, "document", old.id)
    await audit.log(session, ctx.user, "project_document_replaced", str(new.id), {"replaces": str(old.id), "version": new.version},
                    audit.client_ip(request))
    await session.commit()
    return (await _out(session, [new]))[0]


@router.delete("/{document_id}", status_code=204)
async def delete_document(request: Request, document_id: uuid.UUID, ctx: ProjectCtx = project_access("editor"),
                          session: AsyncSession = Depends(get_session)):
    """Removes the file, the extracted text and every chunk/embedding. A metadata stub stays (status 'deleted') for the audit trail."""
    doc = await get_child(session, ProjectDocument, ctx.project.id, document_id, "Document")
    if doc.status == "deleted":
        raise HTTPException(404, "Document not found")
    if not _can_modify(ctx, doc):
        raise HTTPException(403, "Only the owner or the uploader can delete this document")
    lineage = (await session.execute(select(ProjectDocument).where(
        ProjectDocument.project_id == ctx.project.id, ProjectDocument.lineage_id == doc.lineage_id,
        ProjectDocument.status != "deleted"))).scalars().all()
    for d in lineage:       # every version goes: nothing of a deleted document may stay retrievable or downloadable
        await project_index.drop_chunks(session, ctx.project.id, "document", d.id)
        await project_index.invalidate_derived(session, ctx.project.id, "document", d.id)
        d.status, d.extracted = "deleted", []
    await audit.log(session, ctx.user, "project_document_deleted", str(doc.id),
                    {"project_id": str(ctx.project.id), "versions": len(lineage)}, audit.client_ip(request))
    await session.commit()
    for d in lineage:
        project_docs.remove(ctx.project.id, d.storage_key)
