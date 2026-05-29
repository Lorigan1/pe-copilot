"""Pydantic models for the dashboard views."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.company import Company
from app.models.task import Task
from app.models.update import ProcessingStatus, SourceFileType


class CompanySnapshot(BaseModel):
    """A single company's current state for the dashboard."""

    id: str
    name: str
    sector: str
    health_status: str  # green | amber | red
    health_reasons: list[str]
    last_update_at: str | None  # ISO timestamp or None
    latest_period: str
    latest_metrics: dict[str, float | int | None]
    latest_summary: str
    latest_risks: list[str]
    pending_tasks: int


class PortfolioView(BaseModel):
    """The complete portfolio dashboard payload."""

    fund_id: str
    fund_name: str
    total_companies: int
    companies_green: int
    companies_amber: int
    companies_red: int
    companies: list[CompanySnapshot]


class UpdateSummaryDetail(BaseModel):
    """Update detail for the company timeline (excludes bulky extracted_text)."""

    id: str
    received_at: datetime
    source_file_type: SourceFileType
    metrics_period: str = ""
    processing_status: ProcessingStatus = ProcessingStatus.PENDING
    llm_confidence: float = 0.0
    llm_summary: str = ""
    llm_risks: list[str] = []
    llm_action_items: list[str] = []
    normalised_metrics: dict[str, float | int | None] = {}
    variances: dict[str, float] = {}
    missing_metrics: list[str] = []
    raw_file_urls: list[str] = []  # GCS paths — UI uses /api/v1/files/download endpoint


class CompanyDetailView(BaseModel):
    """Complete company detail payload — profile, updates, tasks, and trends."""

    company: Company
    updates: list[UpdateSummaryDetail]
    pending_tasks: list[Task]
    metrics_history: dict[str, list[dict[str, Any]]]
