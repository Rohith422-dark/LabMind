"""Document ingestion: background job (parse -> OCR fallback -> metadata/steps -> chunk+embed)
and the atomic versioned publish."""
import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session_maker
from app.models.tables import Chunk, Document, DocumentFile, IngestJob, KnowledgeGap, SopStep, User
from app.services import answer_cache, audit, llm, parser, step_extractor
from app.services.chunker import ChunkOut, chunk
from app.services.notify import notify
from app.services.parser import Block, ParseError, ParsedDoc

log = logging.getLogger("sla.ingest")


class PublishError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


@dataclass
class Prepared:
    chunks: list[ChunkOut]
    vectors: list[list[float]]
    page_count: int | None
    file_type: str
    full_text: str


# job_id -> Prepared (single uvicorn worker, so in-process is consistent). Lost on restart -> recomputed.
PREPARED: dict[uuid.UUID, Prepared] = {}


async def _set(job_id: uuid.UUID, **kw) -> None:
    async with session_maker()() as s:
        await s.execute(update(IngestJob).where(IngestJob.id == job_id).values(**kw))
        await s.commit()


async def _ocr_pages(doc: ParsedDoc, data: bytes) -> list[int]:
    done = []
    for pno in doc.scanned_pages:
        try:
            png = await asyncio.to_thread(parser.render_page_png, data, pno)
            txt = await llm.ocr_image(png)
        except llm.LLMError as e:
            log.warning("OCR failed on page %s: %s", pno, e)
            continue
        if txt.strip():
            page = doc.pages[pno - 1]
            page.blocks = [Block(t.strip()) for t in txt.split("\n\n") if t.strip()]
            page.ocr = True
            done.append(pno)
    return done


async def prepare(data: bytes) -> tuple[ParsedDoc, Prepared, list[int]]:
    doc = await asyncio.to_thread(parser.parse, data)
    ocr_done = await _ocr_pages(doc, data) if doc.file_type == "pdf" and doc.scanned_pages else []
    chunks = await asyncio.to_thread(chunk, doc)
    if not chunks:
        raise ParseError("No readable text was found in this document.")
    vectors = await llm.embed([c.text for c in chunks], "RETRIEVAL_DOCUMENT")
    return doc, Prepared(chunks, vectors, doc.page_count, doc.file_type, doc.full_text), ocr_done


async def run_job(job_id: uuid.UUID) -> None:
    try:
        async with session_maker()() as s:
            job = await s.get(IngestJob, job_id)
            data, filename = job.file_bytes, job.filename
        await _set(job_id, status="parsing", progress=10)
        doc = await asyncio.to_thread(parser.parse, data)
        warnings: list[str] = []
        ocr_done: list[int] = []
        if doc.file_type == "pdf" and doc.scanned_pages:
            await _set(job_id, status="parsing", progress=25)
            ocr_done = await _ocr_pages(doc, data)
            missed = [p for p in doc.scanned_pages if p not in ocr_done]
            if missed:
                warnings.append(f"Page(s) {', '.join(map(str, missed))} look scanned and could not be transcribed.")
        await _set(job_id, status="extracting", progress=45)
        meta = await step_extractor.extract_metadata(doc, filename)
        steps: list[step_extractor.StepOut] = []
        if meta.doc_type in ("SOP", "protocol"):
            steps, warn = await step_extractor.extract_steps(doc)
            if warn:
                warnings.append(warn)
        await _set(job_id, status="embedding", progress=70)
        chunks = await asyncio.to_thread(chunk, doc)
        if not chunks:
            raise ParseError("No readable text was found in this document.")
        vectors = await llm.embed([c.text for c in chunks], "RETRIEVAL_DOCUMENT")
        PREPARED[job_id] = Prepared(chunks, vectors, doc.page_count, doc.file_type, doc.full_text)
        preview = {
            "metadata": meta.model_dump(),
            "steps": [{"step_no": s.step_no, "action": s.action,
                       "parameters": step_extractor.params_to_dict(s.parameters),
                       "is_critical": s.is_critical, "source_page": s.source_page} for s in steps],
            "page_count": doc.page_count, "file_type": doc.file_type, "chunk_count": len(chunks),
            "ocr_pages": ocr_done, "warnings": warnings,
        }
        await _set(job_id, status="ready", progress=100, preview=preview)
    except ParseError as e:
        await _set(job_id, status="failed", error=str(e))
    except llm.LLMError as e:
        await _set(job_id, status="failed", error=f"AI step failed: {e}")
    except Exception:  # noqa: BLE001  never crash, never leak a stack trace
        log.exception("ingest job %s crashed", job_id)
        await _set(job_id, status="failed", error="Could not process this document. It may be damaged or unusual.")


async def create_job(session: AsyncSession, user: User, filename: str, data: bytes) -> uuid.UUID:
    parser.sniff(data)  # raises ParseError for non PDF/DOCX
    if len(data) > parser.MAX_BYTES:
        raise ParseError("File is larger than 10 MB.")
    job = IngestJob(user_id=user.id, filename=filename[:200], file_bytes=data, status="queued")
    session.add(job)
    await session.flush()
    return job.id


def start(job_id: uuid.UUID) -> None:
    asyncio.get_running_loop().create_task(run_job(job_id))


async def publish(session: AsyncSession, user: User, job: IngestJob, meta: dict, steps: list[dict],
                  gap_id: uuid.UUID | None, ip: str | None) -> Document:
    """One transaction: supersede previous effective version, insert new one, chunks, steps, audit."""
    if job.status == "published" and job.document_id:
        return await session.get(Document, job.document_id)  # idempotent
    if job.status != "ready":
        raise PublishError("This upload is not ready to publish yet.", 409)
    prep = PREPARED.get(job.id)
    if prep is None:  # server restarted since preview: rebuild
        _, prep, _ = await prepare(job.file_bytes)

    code = meta["doc_code"].strip()
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:c))"), {"c": code})
    prev_max = (await session.execute(select(text("max(version)")).select_from(Document)
                                      .where(Document.doc_code == code))).scalar()
    if prev_max and not (meta.get("change_note") or "").strip():
        raise PublishError("A change note is required when publishing a new version of an existing document.")
    version = (prev_max or 0) + 1

    await session.execute(update(Document).where(Document.doc_code == code, Document.status == "effective")
                          .values(status="superseded"))
    await session.execute(update(Chunk).where(Chunk.doc_code == code, Chunk.status == "effective")
                          .values(status="superseded"))

    from datetime import datetime, timezone
    doc = Document(doc_code=code, title=meta["title"], doc_type=meta["doc_type"], version=version,
                   status="effective", department=meta.get("department") or None,
                   equipment=meta.get("equipment") or None, uploaded_by=user.id,
                   change_note=(meta.get("change_note") or None), effective_date=datetime.now(timezone.utc),
                   file_type=prep.file_type, page_count=prep.page_count, full_text=prep.full_text)
    session.add(doc)
    await session.flush()
    session.add(DocumentFile(document_id=doc.id, filename=job.filename,
                             mime="application/pdf" if prep.file_type == "pdf"
                             else "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                             bytes=job.file_bytes, sha256=hashlib.sha256(job.file_bytes).hexdigest()))
    rows = [dict(seq=i, document_id=doc.id, doc_code=code, title=doc.title, version=version, status="effective",
                 page=c.page, section=c.section, department=doc.department, text=c.text, ocr=c.ocr,
                 text_hash=c.text_hash, embedding=v) for i, (c, v) in enumerate(zip(prep.chunks, prep.vectors))]
    for i in range(0, len(rows), 200):
        await session.execute(insert(Chunk), rows[i:i + 200])
    if steps:
        await session.execute(insert(SopStep), [
            dict(document_id=doc.id, step_no=int(s["step_no"]), action=s["action"], parameters=s.get("parameters") or {},
                 is_critical=bool(s.get("is_critical")), source_page=s.get("source_page"), reviewed=bool(s.get("reviewed")))
            for s in steps])

    if gap_id:
        gap = await session.get(KnowledgeGap, gap_id)
        if gap:
            gap.status = "resolved"
            gap.linked_document_id = doc.id
            await notify(session, gap.requested_by,
                         f"A new document for your question is now available: {doc.doc_code} v{version} - {doc.title}",
                         f"/sops/{doc.id}")
    await answer_cache.invalidate_doc(session, code)
    job.status, job.document_id = "published", doc.id
    await audit.log(session, user, "document_published", f"{code} v{version}",
                    {"document_id": str(doc.id), "title": doc.title, "change_note": meta.get("change_note"),
                     "gap_id": str(gap_id) if gap_id else None}, ip)
    PREPARED.pop(job.id, None)
    return doc


async def retire(session: AsyncSession, user: User, doc: Document, reason: str, ip: str | None) -> None:
    if doc.status != "effective":
        raise PublishError("Only an effective document can be retired.", 409)
    doc.status, doc.retire_reason = "retired", reason
    await session.execute(update(Chunk).where(Chunk.document_id == doc.id).values(status="retired"))
    await answer_cache.invalidate_doc(session, doc.doc_code)
    await audit.log(session, user, "document_retired", f"{doc.doc_code} v{doc.version}", {"reason": reason}, ip)
