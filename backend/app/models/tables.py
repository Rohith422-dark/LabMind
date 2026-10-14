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
    reserved_quantity: Mapped[float] = mapped_column(Numeric, default=0, server_default=text("0"))
    availability: Mapped[str] = mapped_column(String(16), default="active", server_default=text("'active'"))
    row_version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    __table_args__ = (
        CheckConstraint("quantity_available >= 0", name="ck_lot_qty_nonneg"),
        CheckConstraint("reserved_quantity >= 0 AND reserved_quantity <= quantity_available", name="ck_lot_reserved"),
        CheckConstraint(_in("availability", ("active", "quarantined", "unavailable")), name="ck_lot_availability"),
    )


REQUEST_STATUSES = ("submitted", "under_review", "needs_clarification", "approved", "rejected", "fulfilled")


class ReagentRequest(Base):
    __tablename__ = "reagent_requests"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **PK)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    reagent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reagents.id"))
    reagent_name_text: Mapped[str | None] = mapped_column(String(200))   # reagent not yet in the register
    quantity: Mapped[float] = mapped_column(Numeric)
    unit: Mapped[str | None] = mapped_column(String(16))
    purpose: Mapped[str | None] = mapped_column(Text)                     # the stated reason
    details: Mapped[str | None] = mapped_column(Text)
    urgency: Mapped[str] = mapped_column(String(10), default="normal", server_default=text("'normal'"))
    experiment_ref: Mapped[str | None] = mapped_column(String(120))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20), default="submitted")
    handled_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reject_reason: Mapped[str | None] = mapped_column(Text)
    issued_lot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reagent_lots.id"))
    reserved_lot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reagent_lots.id"))
    reserved_quantity: Mapped[float] = mapped_column(Numeric, default=0, server_default=text("0"))
    fulfilment_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **NOW)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(_in("status", REQUEST_STATUSES), name="ck_req_status"),
        CheckConstraint(_in("urgency", ("low", "normal", "high", "urgent")), name="ck_req_urgency"),
        CheckConstraint("quantity > 0", name="ck_req_qty_pos"),
        CheckConstraint("reagent_id IS NOT NULL OR reagent_name_text IS NOT NULL", name="ck_req_reagent"),
        Index("ix_reagent_requests_status", "status"),
    )


class RequestEvent(Base):
    """Append-only timeline of a request: status changes and comments (with actor and timestamp)."""
    __tablename__ = "request_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reagent_requests.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))            # status | comment
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str | None] = mapped_column(String(20))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **NOW)
    __table_args__ = (CheckConstraint(_in("kind", ("status", "comment")), name="ck_req_event_kind"),)


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
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
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
    kind: Mapped[str | None] = mapped_column(String(40))
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


# =====================================================================  projects
PROJECT_ROLES = ("owner", "editor", "viewer")


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **PK)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    objectives: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(String(80))
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=text("'{}'"))
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    password_hash: Mapped[str | None] = mapped_column(Text)    # argon2id; NULL = no join password configured
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **NOW)


class ProjectMember(Base):
    """Single source of truth for access. The owner also has a row (role = 'owner')."""
    __tablename__ = "project_members"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **PK)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(10))
    added_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **NOW)
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_member"),
        CheckConstraint(_in("role", PROJECT_ROLES), name="ck_member_role"),
        Index("uq_project_one_owner", "project_id", unique=True, postgresql_where=text("role = 'owner'")),
    )


class ProjectAccessRequest(Base):
    """A user who proved knowledge of the project password asks the owner for access. The password alone grants nothing."""
    __tablename__ = "project_access_requests"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **PK)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="pending")
    role_granted: Mapped[str | None] = mapped_column(String(10))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **NOW)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(_in("status", ("pending", "approved", "denied")), name="ck_access_req_status"),
        Index("uq_access_req_pending", "project_id", "user_id", unique=True, postgresql_where=text("status = 'pending'")),
    )


class ProjectPasswordAttempt(Base):
    __tablename__ = "project_password_attempts"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Experiment(Base):
    __tablename__ = "experiments"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **PK)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    identifier: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(200))
    performed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    objective: Mapped[str | None] = mapped_column(Text)
    reagents: Mapped[list] = mapped_column(JSONB, default=list)        # [{name, reagent_id?, lot_no?, quantity?, unit?}]
    equipment: Mapped[list] = mapped_column(JSONB, default=list)       # [{name, id?}]
    materials: Mapped[list] = mapped_column(JSONB, default=list)
    parameters: Mapped[list] = mapped_column(JSONB, default=list)      # [{name, value?:number, text_value?, unit?, note?}]
    conditions: Mapped[dict] = mapped_column(JSONB, default=dict)      # free-form key/value (temperature, medium, ...)
    custom_fields: Mapped[dict] = mapped_column(JSONB, default=dict)   # discipline-specific, schema-less
    procedure_refs: Mapped[list] = mapped_column(JSONB, default=list)  # [{document_id?, text}]
    observations: Mapped[str | None] = mapped_column(Text)
    results: Mapped[str | None] = mapped_column(Text)
    conclusions: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(String(14), default="unknown")
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=text("'{}'"))
    links: Mapped[list] = mapped_column(JSONB, default=list)           # [{experiment_id, relation}]
    attachments: Mapped[list] = mapped_column(JSONB, default=list)     # [project_document ids]
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **NOW)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))   # soft delete: history is retained
    voided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    tsv = mapped_column(TSVECTOR, Computed(
        "to_tsvector('english', coalesce(identifier,'') || ' ' || coalesce(title,'') || ' ' || coalesce(objective,'') || ' ' "
        "|| coalesce(observations,'') || ' ' || coalesce(results,'') || ' ' || coalesce(conclusions,''))", persisted=True))
    __table_args__ = (
        UniqueConstraint("project_id", "identifier", name="uq_experiment_identifier"),
        CheckConstraint(_in("outcome", ("success", "failure", "inconclusive", "unknown")), name="ck_experiment_outcome"),
        Index("ix_experiments_tsv", "tsv", postgresql_using="gin"),
        Index("ix_experiments_project_performed", "project_id", "performed_at"),
    )


class ExperimentVersion(Base):
    """Append-only: every create/edit/void stores the full record as it was, so history is never overwritten."""
    __tablename__ = "experiment_versions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    experiment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSONB)
    changed_fields: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=text("'{}'"))
    change_note: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **NOW)
    __table_args__ = (UniqueConstraint("experiment_id", "version", name="uq_experiment_version"),)


class ProjectDocument(Base):
    __tablename__ = "project_documents"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **PK)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    lineage_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)   # same for all versions of one document
    version: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(240))
    category: Mapped[str | None] = mapped_column(String(80))
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(8))
    mime: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(120))       # server-generated; never derived from the filename
    status: Mapped[str] = mapped_column(String(12), default="ready")   # ready | superseded | deleted
    page_count: Mapped[int | None] = mapped_column(Integer)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[list] = mapped_column(JSONB, default=list)
    extracted: Mapped[list] = mapped_column(JSONB, default=list)     # [{page, section, text}] kept for viewing / re-indexing
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **NOW)
    __table_args__ = (
        CheckConstraint(_in("status", ("ready", "superseded", "deleted")), name="ck_pdoc_status"),
        CheckConstraint(_in("file_type", ("pdf", "docx", "txt", "csv", "md")), name="ck_pdoc_type"),
        UniqueConstraint("lineage_id", "version", name="uq_pdoc_lineage_version"),
    )


class ProjectChunk(Base):
    """Retrieval unit. EVERY row carries project_id; every query filters on it. Rows of replaced/deleted sources are deleted."""
    __tablename__ = "project_chunks"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **PK)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    source_type: Mapped[str] = mapped_column(String(12))       # document | experiment
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    source_version: Mapped[int] = mapped_column(Integer, default=1)
    label: Mapped[str] = mapped_column(Text)                   # human-readable source name for citations
    seq: Mapped[int] = mapped_column(Integer, default=0)
    page: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768))
    tsv = mapped_column(TSVECTOR, Computed("to_tsvector('english', text)", persisted=True))
    __table_args__ = (
        CheckConstraint(_in("source_type", ("document", "experiment")), name="ck_pchunk_type"),
        Index("ix_pchunks_embedding_hnsw", "embedding", postgresql_using="hnsw",
              postgresql_ops={"embedding": "vector_cosine_ops"}),
        Index("ix_pchunks_tsv", "tsv", postgresql_using="gin"),
    )


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text)            # AI-generated, UNVERIFIED context; never evidence
    summary_through: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))   # number of turns folded into the summary
    summary_stale: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    external_allowed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))   # user chose "allow for this conversation"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **NOW)


class Memory(Base):
    __tablename__ = "memories"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **PK)
    scope: Mapped[str] = mapped_column(String(10))                 # user | project
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)   # owner / author
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(14), default="note")
    content: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(14), default="user")   # user | ai_suggested (never a verified record)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    source_refs: Mapped[list] = mapped_column(JSONB, default=list)    # [{type, id, version}] for stale detection
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **NOW)
    __table_args__ = (
        CheckConstraint(_in("scope", ("user", "project")), name="ck_memory_scope"),
        CheckConstraint(_in("kind", ("preference", "terminology", "finding", "note")), name="ck_memory_kind"),
        CheckConstraint(_in("origin", ("user", "ai_suggested")), name="ck_memory_origin"),
        CheckConstraint("(scope = 'project') = (project_id IS NOT NULL)", name="ck_memory_scope_project"),
    )
