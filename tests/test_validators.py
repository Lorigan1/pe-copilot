"""Tests for Layer 3.5 — deterministic financial metric validation."""

import pytest

from app.services.validators import (
    MetricValidationResult,
    validate_metrics,
)


class TestValidMetrics:
    """Normal metrics should pass all checks."""

    def test_valid_metrics_pass(self):
        """Healthy SME metrics produce no warnings or errors."""
        metrics = {
            "revenue": 2_500_000,
            "gross_profit": 1_200_000,
            "ebitda": 600_000,
            "net_income": 350_000,
            "cash_balance": 800_000,
            "total_debt": 1_000_000,
            "net_assets": 2_000_000,
            "operating_cashflow": 500_000,
            "headcount": 45,
        }
        result = validate_metrics(metrics)
        assert result.is_valid is True
        assert result.warnings == []
        assert result.errors == []

    def test_empty_metrics_pass(self):
        """Empty metrics dict returns a valid result (nothing to check)."""
        result = validate_metrics({})
        assert result.is_valid is True


class TestSignConstraints:
    """Revenue, gross_profit, headcount must be >= 0."""

    def test_negative_revenue_flagged(self):
        metrics = {"revenue": -500_000, "ebitda": 100_000}
        result = validate_metrics(metrics)
        assert any("revenue" in w and "negative" in w for w in result.warnings)

    def test_negative_gross_profit_flagged(self):
        metrics = {"revenue": 1_000_000, "gross_profit": -200_000}
        result = validate_metrics(metrics)
        assert any("gross_profit" in w and "negative" in w for w in result.warnings)

    def test_negative_headcount_flagged(self):
        metrics = {"headcount": -5}
        result = validate_metrics(metrics)
        assert any("headcount" in w and "negative" in w for w in result.warnings)

    def test_negative_net_income_ok(self):
        """net_income CAN be negative (a loss) — should NOT be flagged."""
        metrics = {"revenue": 1_000_000, "net_income": -50_000}
        result = validate_metrics(metrics)
        assert not any("net_income" in w for w in result.warnings)


class TestAccountingIdentities:
    """Cross-metric consistency: gross_profit <= revenue, ebitda <= gross_profit."""

    def test_gross_profit_exceeds_revenue(self):
        metrics = {"revenue": 1_000_000, "gross_profit": 1_200_000}
        result = validate_metrics(metrics)
        assert any("gross_profit" in w and "exceeds" in w and "revenue" in w for w in result.warnings)

    def test_ebitda_exceeds_gross_profit(self):
        metrics = {"gross_profit": 500_000, "ebitda": 700_000}
        result = validate_metrics(metrics)
        assert any("ebitda" in w and "exceeds" in w and "gross_profit" in w for w in result.warnings)

    def test_within_tolerance_ok(self):
        """5% tolerance for rounding — gross_profit slightly above revenue should pass."""
        metrics = {"revenue": 1_000_000, "gross_profit": 1_040_000}  # 4% over
        result = validate_metrics(metrics)
        assert not any("exceeds" in w for w in result.warnings)

    def test_exactly_at_tolerance_boundary(self):
        """At exactly 5% over — should still pass (tolerance is inclusive)."""
        metrics = {"revenue": 1_000_000, "gross_profit": 1_050_000}  # 5% over = threshold
        result = validate_metrics(metrics)
        assert not any("exceeds" in w for w in result.warnings)


class TestMagnitudeBounds:
    """Catch pence-vs-pounds and other unit errors."""

    def test_magnitude_bound_exceeded(self):
        """Value > £10B triggers a warning."""
        metrics = {"revenue": 15_000_000_000}  # £15B
        result = validate_metrics(metrics)
        assert any("magnitude" in w and "revenue" in w for w in result.warnings)

    def test_normal_magnitude_ok(self):
        """£50M revenue is fine for a portfolio company."""
        metrics = {"revenue": 50_000_000}
        result = validate_metrics(metrics)
        assert not any("magnitude" in w for w in result.warnings)

    def test_headcount_over_max(self):
        metrics = {"headcount": 200_000}
        result = validate_metrics(metrics)
        assert any("headcount" in w and "100,000" in w for w in result.warnings)


class TestZeroRevenue:
    """Revenue = 0 with other P&L non-zero is likely extraction failure."""

    def test_zero_revenue_with_other_pnl(self):
        metrics = {"revenue": 0, "ebitda": 500_000}
        result = validate_metrics(metrics)
        assert any("revenue is 0" in w for w in result.warnings)

    def test_zero_revenue_all_zeros_ok(self):
        """All zeros is fine (pre-revenue company or empty data)."""
        metrics = {"revenue": 0, "ebitda": 0, "net_income": 0}
        result = validate_metrics(metrics)
        assert not any("revenue is 0" in w for w in result.warnings)

    def test_revenue_none_not_flagged(self):
        """None revenue (missing) is different from 0 — don't flag."""
        metrics = {"revenue": None, "ebitda": 500_000}
        result = validate_metrics(metrics)
        assert not any("revenue is 0" in w for w in result.warnings)


class TestVarianceSpikes:
    """Extreme period-over-period changes may indicate extraction errors."""

    def test_extreme_variance_flagged(self):
        """A 600% change should trigger a warning."""
        metrics = {"revenue": 7_000_000}
        variances = {"revenue": 6.0}  # 600%
        result = validate_metrics(metrics, variances=variances)
        assert any("revenue" in w and "600%" in w for w in result.warnings)

    def test_normal_variance_ok(self):
        """A 15% change is perfectly normal — no warning."""
        metrics = {"revenue": 1_150_000}
        variances = {"revenue": 0.15}
        result = validate_metrics(metrics, variances=variances)
        assert not any("revenue" in w for w in result.warnings)

    def test_negative_spike_flagged(self):
        """A -600% drop should also be flagged."""
        metrics = {"revenue": 100_000}
        variances = {"revenue": -6.0}
        result = validate_metrics(metrics, variances=variances)
        assert any("revenue" in w and "decreased" in w for w in result.warnings)


class TestValidationIntegration:
    """is_valid flag and overall behaviour."""

    def test_warnings_dont_create_errors(self):
        """Warnings alone don't set is_valid=False (no hard errors in current checks)."""
        metrics = {"revenue": -500_000}  # Warning, not error
        result = validate_metrics(metrics)
        assert result.is_valid is True  # Warnings only
        assert len(result.warnings) > 0

    def test_none_values_skipped(self):
        """Metrics with None values should be skipped gracefully."""
        metrics = {"revenue": None, "ebitda": None, "headcount": None}
        result = validate_metrics(metrics)
        assert result.is_valid is True
        assert result.warnings == []
