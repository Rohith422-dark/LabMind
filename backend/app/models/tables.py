import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Computed, Date, DateTime, ForeignKey, Index,
    Integer, LargeBinary, Numeric, String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

PK = dict(primary_key=True, server_default=text("gen_random_uuid()"))
NOW = dict(server_default=func.now())


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **PK)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(24))
    department: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **NOW)
    __table_args__ = (CheckConstraint(_in("role", ("scientist", "lab_analyst", "senior_analyst", "admin")), name="ck_users_role"),)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **PK)
    doc_code: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(Text)
    doc_type: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16))
    department: Mapped[str | None] = mapped_column(String(80))
    equipment: Mapped[str | None] = mapped_column(String(120))
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    change_note: Mapped[str | None] = mapped_column(Text)
    effective_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    file_type: Mapped[str] = mapped_column(String(8))
    page_count: Mapped[int | None] = mapped_column(Integer)
    full_text: Mapped[str | None] = mapped_column(Text)
    retire_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **NOW)
    __table_args__ = (
        UniqueConstraint("doc_code", "version", name="uq_doc_code_version"),
        CheckConstraint(_in("doc_type", ("SOP", "protocol", "troubleshooting_guide", "manual")), name="ck_doc_type"),
        CheckConstraint(_in("status", ("draft", "effective", "superseded", "retired")), name="ck_doc_status"),
        CheckConstraint(_in("file_type", ("pdf", "docx")), name="ck_doc_file_type"),
        Index("uq_one_effective_per_code", "doc_code", unique=True, postgresql_where=text("status = 'effective'")),
        Index("ix_documents_code_trgm", "doc_code", postgresql_using="gin", postgresql_ops={"doc_code": "gin_trgm_ops"}),
        Index("ix_documents_title_trgm", "title", postgresql_using="gin", postgresql_ops={"title": "gin_trgm_ops"}),
    )


class DocumentFile(Base):
    __tablename__ = "document_files"
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    filename: Mapped[str] = mapped_column(Text)
    mime: Mapped[str] = mapped_column(String(120))
    bytes: Mapped[bytes] = mapped_column(LargeBinary)
    sha256: Mapped[str] = mapped_column(String(64))


class SopStep(Base):
    __tablename__ = "sop_steps"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **PK)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    step_no: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(Text)
    parameters: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)
    source_page: Mapped[int | None] = mapped_column(Integer)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **PK)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    doc_code: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    page: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(Text)
    department: Mapped[str | None] = mapped_column(String(80))
    text: Mapped[str] = mapped_column(Text)
    ocr: Mapped[bool] = mapped_column(Boolean, default=False)
    text_hash: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768))
    tsv = mapped_column(TSVECTOR, Computed("to_tsvector('english', text)", persisted=True))
    __table_args__ = (
        Index("ix_chunks_embedding_hnsw", "embedding", postgresql_using="hnsw",
              postgresql_ops={"embedding": "vector_cosine_ops"}),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
    )


class Reagent(Base):
    __tablename__ = "reagents"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **PK)
    name: Mapped[str] = mapped_column(String(200))
    cas_number: Mapped[str | None] = mapped_column(String(32))
    formula: Mapped[str | None] = mapped_column(String(120))
    hazard_classes: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=text("'{}'"))
    hazard_statements: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=text("'{}'"))
    pubchem_cid: Mapped[int | None] = mapped_column(Integer)
    storage_conditions: Mapped[str | None] = mapped_column(Text)
    supplier: Mapped[str | None] = mapped_column(String(160))
    reorder_level: Mapped[float | None] = mapped_column(Numeric)
    unit: Mapped[str | None] = mapped_column(String(16))
    __table_args__ = (
        Index("ix_reagents_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
    )


class ReagentLot(Base):
    __tablename__ = "reagent_lots"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **PK)
    reagent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reagents.id"), index=True)
    lot_no: Mapped[str] = mapped_column(String(80))
    grade: Mapped[str | None] = mapped_column(String(60))
    capacity: Mapped[float] = mapped_column(Numeric)
    quantity_available: Mapped[float] = mapped_column(Numeric)
    location: Mapped[str | None] = mapped_column(String(120))
    expiry_date: Mapped[date | None] = mapped_column(Date)
    received_date: Mapped[date | None] = mapped_column(Date)
    storage_conditions: Mapped[str | None] = mapped_column(Text)
    supplier: Mapped[str | None] = mapped_column(String(160))
    __table_args__ = (CheckConstraint("quantity_available >= 0", name="ck_lot_qty_nonneg"),)


class ReagentRequest(Base):
    __tablename__ = "reagent_requests"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **PK)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    reagent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reagents.id"))
    quantity: Mapped[float] = mapped_column(Numeric)
    purpose: Mapped[str | None] = mapped_column(Text)
    experiment_ref: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(12), default="pending")
    handled_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reject_reason: Mapped[str | None] = mapped_column(Text)
    issued_lot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reagent_lots.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **NOW)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(_in("status", ("pending", "issued", "rejected")), name="ck_req_status"),
        CheckConstraint("quantity > 0", name="ck_req_qty_pos"),
    )


class InventoryTransaction(Base):
    __tablename__ = "inventory_transactions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **PK)
    lot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reagent_lots.id"), index=True)
    type: Mapped[str] = mapped_column(String(12))
    quantity: Mapped[float] = mapped_column(Numeric)
    performed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    issued_to: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), **NOW)
    __table_args__ = (CheckConstraint(_in("type", ("received", "issued", "returned", "adjusted", "disposed")), name="ck_tx_type"),)


class ChatHistory(Base):
    __tablename__ = "chat_history"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **PK)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(10), default="internal")
    sources: Mapped[list] = mapped_column(JSONB, default=list)
    feedback: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **NOW)
    __table_args__ = (CheckConstraint(_in("source_type", ("internal", "external")), name="ck_chat_source"),)


class KnowledgeGap(Base):
    __tablename__ = "knowledge_gaps"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **PK)
    question: Mapped[str] = mapped_column(Text)
    normalized_question: Mapped[str] = mapped_column(Text, index=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(16), default="open")
    similar_count: Mapped[int] = mapped_column(Integer, default=1)
    linked_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **NOW)
    __table_args__ = (CheckConstraint(_in("status", ("open", "sop_requested", "sop_uploaded", "resolved")), name="ck_gap_status"),)


class TroubleshootingSession(Base):
    __tablename__ = "troubleshooting_sessions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **PK)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    symptom: Mapped[str | None] = mapped_column(Text)
    narrated_steps: Mapped[list] = mapped_column(JSONB, default=list)
    comparison: Mapped[list] = mapped_column(JSONB, default=list)
    questions_asked: Mapped[list] = mapped_column(JSONB, default=list)
    conversation: Mapped[list] = mapped_column(JSONB, default=list)
    diagnosis: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **NOW)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **PK)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    message: Mapped[str] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **NOW)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    username: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[str | None] = mapped_column(String(24))
    action: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    ip: Mapped[str | None] = mapped_column(String(64))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), **NOW)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class IngestJob(Base):
    __tablename__ = "ingest_jobs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **PK)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    preview: Mapped[dict | None] = mapped_column(JSONB)
    file_bytes: Mapped[bytes | None] = mapped_column(LargeBinary)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **NOW)
    __table_args__ = (CheckConstraint(_in("status", ("queued", "parsing", "extracting", "embedding", "ready", "failed", "published")), name="ck_job_status"),)


class AnswerCache(Base):
    __tablename__ = "answer_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    answer: Mapped[str] = mapped_column(Text)
    sources: Mapped[list] = mapped_column(JSONB, default=list)
    doc_versions_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **NOW)
