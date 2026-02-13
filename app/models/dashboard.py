"""Pydantic models for the dashboard views."""

from pydantic import BaseModel


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
