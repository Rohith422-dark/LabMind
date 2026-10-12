import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

DocType = Literal["SOP", "protocol", "troubleshooting_guide", "manual"]
DocStatus = Literal["draft", "effective", "superseded", "retired"]


class DocumentOut(BaseModel):
    id: uuid.UUID
    doc_code: str
    title: str
    doc_type: DocType
    version: int
    status: DocStatus
    department: str | None = None
    equipment: str | None = None
    change_note: str | None = None
    effective_date: datetime | None = None
    file_type: Literal["pdf", "docx"]
    page_count: int | None = None
    retire_reason: str | None = None
    created_at: datetime
    model_config = {"from_attributes": True}


class StepOutSchema(BaseModel):
    step_no: int
    action: str
    parameters: dict = {}
    is_critical: bool = False
    source_page: int | None = None
    reviewed: bool = False
    model_config = {"from_attributes": True}


class TextSection(BaseModel):
    section: str | None = None
    text: str
    chunk_id: str


class DocumentDetail(DocumentOut):
    steps: list[StepOutSchema] = []
    text_sections: list[TextSection] = []   # DOCX viewer


class JobOut(BaseModel):
    id: uuid.UUID
    filename: str
    status: Literal["queued", "parsing", "extracting", "embedding", "ready", "failed", "published"]
    progress: int
    error: str | None = None
    preview: dict | None = None
    document_id: uuid.UUID | None = None
    model_config = {"from_attributes": True}


class JobCreated(BaseModel):
    job_id: uuid.UUID


class StepIn(BaseModel):
    step_no: int
    action: str = Field(min_length=1, max_length=1000)
    parameters: dict = {}
    is_critical: bool = False
    source_page: int | None = None
    reviewed: bool = False


class PublishIn(BaseModel):
    job_id: uuid.UUID
    doc_code: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=500)
    doc_type: DocType
    department: str | None = None
    equipment: str | None = None
    change_note: str | None = None
    steps: list[StepIn] = []
    gap_id: uuid.UUID | None = None


class RetireIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class HighlightOut(BaseModel):
    page: int
    page_width: float
    page_height: float
    rects: list[list[float]]
    text: str | None = None
    section: str | None = None
