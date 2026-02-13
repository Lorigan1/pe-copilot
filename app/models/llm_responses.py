"""Pydantic models for validating LLM responses.

These enforce structure on what Claude returns, catching malformed output
before it enters Firestore.
"""

from pydantic import BaseModel, Field


class NormalisationResponse(BaseModel):
    """Expected JSON structure from the normalisation prompt."""

    period: str = Field(..., description="e.g. 'Jan 2026', 'Q4 2025'")
    metrics: dict[str, float | int | None] = Field(
        ..., description="Canonical metric name → numeric value"
    )
    unmapped_data: list[str] = Field(
        default=[],
        description="Notable data that did not map to the schema",
    )
    confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="0–1 confidence in extraction quality",
    )
    notes: str = Field(
        default="",
        description="Any caveats or assumptions made during mapping",
    )


class SummarisationResponse(BaseModel):
    """Expected JSON structure from the summarisation prompt."""

    summary: str = Field(..., description="3–5 sentence summary")
    risks: list[str] = Field(default=[], description="Specific risks or concerns")
    action_items: list[str] = Field(default=[], description="Suggested follow-ups")


class DigestCompanySummary(BaseModel):
    """Per-company block within a digest."""

    company_id: str
    company_name: str
    period: str
    summary: str
    key_metrics: dict[str, float | int | None] = {}
    risks: list[str] = []
    status: str = "green"


class DigestResponse(BaseModel):
    """Expected JSON structure from the digest prompt."""

    overall_summary: str
    company_summaries: list[DigestCompanySummary]
    attention_items: list[str] = Field(
        default=[], description="Cross-portfolio items requiring attention"
    )
