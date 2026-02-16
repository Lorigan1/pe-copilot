"""Pydantic models for the updates collection.

An 'update' represents a single ingested file or email from a portfolio company.
It goes through: pending → processing → completed | needs_review | failed.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ProcessingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class SourceType(str, Enum):
    MANUAL_UPLOAD = "manual_upload"
    EMAIL = "email"
    API = "api"


class SourceFileType(str, Enum):
    EXCEL = "excel"
    CSV = "csv"
    PDF = "pdf"
    EMAIL_TEXT = "email_text"


class UpdateCreate(BaseModel):
    """Created when a new file is ingested (before processing)."""

    fund_id: str
    company_id: str
    source_type: SourceType = SourceType.MANUAL_UPLOAD
    source_file_type: SourceFileType
    source_email_from: str = ""
    source_email_subject: str = ""
    raw_file_urls: list[str] = []
    metrics_period: str = ""  # e.g. "Jan 2026", "Q4 2025"
    file_content_hash: str = ""  # SHA-256 hex digest for dedup


class Update(BaseModel):
    """Full update entity as stored in Firestore."""

    id: str
    fund_id: str
    company_id: str
    received_at: datetime = Field(default_factory=datetime.utcnow)

    # Source info
    source_type: SourceType
    source_file_type: SourceFileType
    source_email_from: str = ""
    source_email_subject: str = ""
    raw_file_urls: list[str] = []

    # Content deduplication
    file_content_hash: str = ""  # SHA-256 hex digest of raw file

    # Extraction (Layer 1)
    extracted_text: str = ""

    # Normalisation (Layer 2 — LLM output)
    normalised_metrics: dict[str, float | int | None] = {}
    metrics_period: str = ""
    metrics_period_start: datetime | None = None
    metrics_period_end: datetime | None = None
    llm_summary: str = ""
    llm_risks: list[str] = []
    llm_action_items: list[str] = []
    llm_confidence: float = 0.0

    # Validation (Layer 3)
    missing_metrics: list[str] = []
    variances: dict[str, float] = {}  # metric_name → % change from previous period

    # Processing state
    processing_status: ProcessingStatus = ProcessingStatus.PENDING
    processing_error: str = ""
    processed_at: datetime | None = None
    reviewed_by: str = ""
    reviewed_at: datetime | None = None


class UpdateSummary(BaseModel):
    """Lightweight update for list views (no extracted_text, etc.)."""

    id: str
    company_id: str
    received_at: datetime
    source_type: SourceType
    source_file_type: SourceFileType
    metrics_period: str = ""
    normalised_metrics: dict[str, float | int | None] = {}
    llm_summary: str = ""
    llm_risks: list[str] = []
    llm_confidence: float = 0.0
    missing_metrics: list[str] = []
    processing_status: ProcessingStatus = ProcessingStatus.PENDING
