"""Pydantic models for the companies collection."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.metric_schema import MetricDefinition


class ReportingContact(BaseModel):
    """A person who sends financial data for this company."""

    name: str
    email: str
    role: str = ""  # e.g. "CFO", "Financial Controller", "Accountant"


class CompanyCreate(BaseModel):
    """Request model for creating a new portfolio company."""

    fund_id: str
    name: str = Field(..., min_length=1, max_length=200)
    sector: str = ""
    primary_contact_name: str = ""
    primary_contact_email: str = ""
    reporting_contacts: list[ReportingContact] = []
    canonical_metrics: list[MetricDefinition] = []
    mapping_instructions: str = Field(
        default="",
        description=(
            "Company-specific instructions for the LLM normaliser, "
            "e.g. 'Revenue is on tab P&L, row 12. They call EBITDA \"Operating Surplus\"'"
        ),
    )
    reporting_frequency: str = Field(
        default="monthly",
        description="monthly | quarterly | varies",
    )
    accounting_system: str = ""  # Xero, Sage, QuickBooks, etc.
    notes: str = ""


class CompanyUpdate(BaseModel):
    """Request model for updating a company."""

    name: str | None = None
    sector: str | None = None
    primary_contact_name: str | None = None
    primary_contact_email: str | None = None
    reporting_contacts: list[ReportingContact] | None = None
    canonical_metrics: list[MetricDefinition] | None = None
    mapping_instructions: str | None = None
    reporting_frequency: str | None = None
    accounting_system: str | None = None
    notes: str | None = None


class Company(BaseModel):
    """Full company entity as stored in Firestore."""

    id: str
    fund_id: str
    name: str
    sector: str = ""
    primary_contact_name: str = ""
    primary_contact_email: str = ""
    reporting_contacts: list[ReportingContact] = []
    canonical_metrics: list[MetricDefinition] = []
    mapping_instructions: str = ""
    reporting_frequency: str = "monthly"
    accounting_system: str = ""
    last_update_at: datetime | None = None
    health_status: str = "green"  # green | amber | red
    health_reasons: list[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    notes: str = ""
