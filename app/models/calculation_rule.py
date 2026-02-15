"""Models for deterministic financial calculations.

Defines label mappings and calculation rules that allow the system to
compute derived metrics (e.g., Gross Profit, EBITDA) from raw line items
before the LLM sees the data. This ensures consistent calculations
across periods, eliminating variance artifacts from blank formula cells.
"""

from pydantic import BaseModel, Field


class LabelMapping(BaseModel):
    """Maps a label in extracted text to an internal metric name.

    Example: "Net Sales" in NorthStar's Sage export → internal name "net_sales"
    """

    label: str = Field(..., description="Label as it appears in the extracted text (e.g., 'Net Sales')")
    metric_name: str = Field(..., description="Internal metric name (e.g., 'net_sales')")


class CalculationRule(BaseModel):
    """A formula for computing a derived metric from other metrics.

    Example: gross_profit = net_sales + cost_of_sales
    (cost_of_sales is negative in the source data, so addition is correct)

    Formulas use internal metric names and support: +, -, *, /, parentheses.
    """

    metric_name: str = Field(
        ..., description="Internal name of the metric to compute (e.g., 'gross_profit')"
    )
    source_label: str = Field(
        ..., description="Label of the row in extracted text to inject the result into (e.g., 'Gross Profit')"
    )
    formula: str = Field(
        ..., description="Arithmetic formula using internal metric names (e.g., 'net_sales + cost_of_sales')"
    )
    description: str = Field(
        default="", description="Human-readable explanation of the calculation"
    )
