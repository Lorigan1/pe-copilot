"""Pydantic models for the metric_schemas collection.

Defines the canonical set of financial metrics a fund tracks.
Each portfolio company's raw data gets normalised to this schema.
"""

from pydantic import BaseModel, Field


class MetricDefinition(BaseModel):
    """A single canonical metric definition."""

    name: str = Field(..., description="Internal name, e.g. 'revenue', 'ebitda'")
    label: str = Field(..., description="Display label, e.g. 'Revenue', 'EBITDA'")
    type: str = Field(
        default="currency",
        description="Metric type: currency | number | percentage | ratio",
    )
    unit: str = Field(default="GBP", description="Unit: GBP | USD | EUR | headcount | etc.")
    category: str = Field(
        default="pnl",
        description="Category: pnl | balance_sheet | cashflow | operational | covenant",
    )
    is_required: bool = Field(
        default=True,
        description="Whether this metric is expected in every update",
    )
    variance_threshold: float = Field(
        default=0.20,
        description="% change that triggers an alert (0.20 = 20%)",
    )


class MetricSchemaCreate(BaseModel):
    """Request model for creating/updating a company's metric schema."""

    metrics: list[MetricDefinition]


# ─── Default metric schema for PE portfolio companies ───
DEFAULT_PE_METRICS: list[MetricDefinition] = [
    MetricDefinition(
        name="revenue",
        label="Revenue",
        type="currency",
        unit="GBP",
        category="pnl",
    ),
    MetricDefinition(
        name="gross_profit",
        label="Gross Profit",
        type="currency",
        unit="GBP",
        category="pnl",
    ),
    MetricDefinition(
        name="ebitda",
        label="EBITDA",
        type="currency",
        unit="GBP",
        category="pnl",
    ),
    MetricDefinition(
        name="net_income",
        label="Net Income",
        type="currency",
        unit="GBP",
        category="pnl",
    ),
    MetricDefinition(
        name="cash_balance",
        label="Cash Balance",
        type="currency",
        unit="GBP",
        category="balance_sheet",
    ),
    MetricDefinition(
        name="total_debt",
        label="Total Debt",
        type="currency",
        unit="GBP",
        category="balance_sheet",
    ),
    MetricDefinition(
        name="net_assets",
        label="Net Assets",
        type="currency",
        unit="GBP",
        category="balance_sheet",
    ),
    MetricDefinition(
        name="operating_cashflow",
        label="Operating Cash Flow",
        type="currency",
        unit="GBP",
        category="cashflow",
    ),
    MetricDefinition(
        name="headcount",
        label="Headcount",
        type="number",
        unit="headcount",
        category="operational",
        is_required=False,
        variance_threshold=0.15,
    ),
]
