"""Layer 3.5 — Deterministic financial metric validation.

Sanity-checks LLM-extracted metrics BEFORE storing. Catches hallucinations,
unit errors, and accounting-identity violations without using LLM tokens.
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Metrics that must be non-negative (sign constraints)
NON_NEGATIVE_METRICS = {"revenue", "gross_profit", "headcount"}

# P&L metrics (used for zero-revenue check)
PNL_METRICS = {"gross_profit", "ebitda", "net_income", "operating_cashflow"}

# Absolute magnitude cap for currency metrics (£10B — catches pence-vs-pounds errors)
CURRENCY_MAGNITUDE_CAP = 10_000_000_000

# Headcount sanity bounds
HEADCOUNT_MAX = 100_000

# Variance spike threshold (500% = 5.0 as a decimal)
VARIANCE_SPIKE_THRESHOLD = 5.0

# Accounting identity pairs: (child, parent) where child <= parent
ACCOUNTING_IDENTITIES = [
    ("gross_profit", "revenue"),
    ("ebitda", "gross_profit"),
]

# Tolerance for accounting identity checks (5% — allows for rounding)
IDENTITY_TOLERANCE = 0.05

# Currency metrics (for magnitude checks)
CURRENCY_METRICS = {
    "revenue", "gross_profit", "ebitda", "net_income",
    "cash_balance", "total_debt", "net_assets", "operating_cashflow",
}


@dataclass
class MetricValidationResult:
    """Result of metric validation checks."""

    is_valid: bool = True
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def validate_metrics(
    metrics: dict[str, float | int | None],
    previous_metrics: dict[str, float | int | None] | None = None,
    variances: dict[str, float] | None = None,
) -> MetricValidationResult:
    """Run all deterministic sanity checks on normalised metrics.

    Args:
        metrics: The LLM-extracted normalised metrics for this period.
        previous_metrics: Metrics from the prior period (for context).
        variances: Pre-calculated period-over-period variances (decimal, e.g. 0.25 = 25%).

    Returns:
        MetricValidationResult with warnings and errors.
    """
    result = MetricValidationResult()

    if not metrics:
        return result

    # 1. Sign constraints
    _check_sign_constraints(metrics, result)

    # 2. Accounting identity checks
    _check_accounting_identities(metrics, result)

    # 3. Magnitude bounds
    _check_magnitude_bounds(metrics, result)

    # 4. Zero-revenue check
    _check_zero_revenue(metrics, result)

    # 5. Variance spike detection
    if variances:
        _check_variance_spikes(variances, result)

    # Set is_valid based on whether there are errors
    result.is_valid = len(result.errors) == 0

    return result


def _check_sign_constraints(
    metrics: dict[str, float | int | None],
    result: MetricValidationResult,
) -> None:
    """Revenue, gross_profit, headcount must be >= 0."""
    for metric in NON_NEGATIVE_METRICS:
        value = metrics.get(metric)
        if value is not None and value < 0:
            result.warnings.append(
                f"{metric} is negative ({value:,.0f}) — expected >= 0"
            )


def _check_accounting_identities(
    metrics: dict[str, float | int | None],
    result: MetricValidationResult,
) -> None:
    """Check that child <= parent within tolerance (e.g. gross_profit <= revenue)."""
    for child_name, parent_name in ACCOUNTING_IDENTITIES:
        child = metrics.get(child_name)
        parent = metrics.get(parent_name)
        if child is None or parent is None:
            continue
        if parent == 0:
            continue
        # Allow child to exceed parent by up to IDENTITY_TOLERANCE
        threshold = abs(parent) * (1 + IDENTITY_TOLERANCE)
        if child > threshold:
            result.warnings.append(
                f"{child_name} ({child:,.0f}) exceeds {parent_name} ({parent:,.0f}) "
                f"— possible extraction error"
            )


def _check_magnitude_bounds(
    metrics: dict[str, float | int | None],
    result: MetricValidationResult,
) -> None:
    """Flag unreasonably large values (likely unit errors like pence vs pounds)."""
    for metric in CURRENCY_METRICS:
        value = metrics.get(metric)
        if value is not None and abs(value) > CURRENCY_MAGNITUDE_CAP:
            result.warnings.append(
                f"{metric} magnitude ({value:,.0f}) exceeds £10B cap "
                f"— possible units error (pence vs pounds?)"
            )

    # Headcount bounds
    headcount = metrics.get("headcount")
    if headcount is not None:
        if headcount < 0:
            result.warnings.append(
                f"headcount is negative ({headcount:,.0f})"
            )
        elif headcount > HEADCOUNT_MAX:
            result.warnings.append(
                f"headcount ({headcount:,.0f}) exceeds {HEADCOUNT_MAX:,} "
                f"— verify this is correct for an SME portfolio company"
            )


def _check_zero_revenue(
    metrics: dict[str, float | int | None],
    result: MetricValidationResult,
) -> None:
    """If revenue is exactly 0 but other P&L metrics are non-zero, flag it."""
    revenue = metrics.get("revenue")
    if revenue is not None and revenue == 0:
        has_nonzero_pnl = any(
            metrics.get(m) not in (None, 0) for m in PNL_METRICS
        )
        if has_nonzero_pnl:
            result.warnings.append(
                "revenue is 0 but other P&L metrics are non-zero "
                "— likely extraction failure"
            )


def _check_variance_spikes(
    variances: dict[str, float],
    result: MetricValidationResult,
) -> None:
    """Flag metrics that changed by more than 500% (possible extraction error)."""
    for metric, variance in variances.items():
        if abs(variance) > VARIANCE_SPIKE_THRESHOLD:
            direction = "increased" if variance > 0 else "decreased"
            pct = abs(variance) * 100
            result.warnings.append(
                f"{metric} {direction} by {pct:.0f}% period-over-period "
                f"— verify this is not an extraction error"
            )
