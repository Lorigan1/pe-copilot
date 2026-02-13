"""Tests for the health scoring service."""

from datetime import datetime, timedelta

import pytest

from app.models.company import Company
from app.models.metric_schema import DEFAULT_PE_METRICS
from app.services.health_scorer import HealthScorer


@pytest.fixture
def scorer():
    return HealthScorer()


@pytest.fixture
def healthy_company():
    return Company(
        id="test-1",
        fund_id="fund-1",
        name="AlphaCo",
        sector="Technology",
        canonical_metrics=DEFAULT_PE_METRICS,
        last_update_at=datetime.utcnow() - timedelta(days=5),
    )


def test_healthy_company_is_green(scorer, healthy_company):
    """Recent update, no issues → green."""
    status, reasons = scorer.score(healthy_company)
    assert status == "green"


def test_stale_company_is_amber(scorer, healthy_company):
    """No update in 25 days → amber."""
    healthy_company.last_update_at = datetime.utcnow() - timedelta(days=25)
    status, reasons = scorer.score(healthy_company)
    assert status == "amber"
    assert any("25 days" in r for r in reasons)


def test_very_stale_company_is_red(scorer, healthy_company):
    """No update in 50 days → red."""
    healthy_company.last_update_at = datetime.utcnow() - timedelta(days=50)
    status, reasons = scorer.score(healthy_company)
    assert status == "red"


def test_large_negative_revenue_variance_is_red(scorer, healthy_company):
    """Revenue dropped 30% → red."""
    status, reasons = scorer.score(
        healthy_company,
        latest_variances={"revenue": -0.30},
    )
    assert status == "red"
    assert any("revenue" in r.lower() for r in reasons)


def test_moderate_variance_is_amber(scorer, healthy_company):
    """Headcount increased 25% → amber (non-critical metric)."""
    status, reasons = scorer.score(
        healthy_company,
        latest_variances={"headcount": 0.25},
    )
    assert status == "amber"


def test_missing_metrics_amber(scorer, healthy_company):
    """1-2 missing metrics → amber."""
    status, reasons = scorer.score(
        healthy_company,
        latest_missing_metrics=["ebitda"],
    )
    assert status == "amber"


def test_many_missing_metrics_red(scorer, healthy_company):
    """3+ missing metrics → red."""
    status, reasons = scorer.score(
        healthy_company,
        latest_missing_metrics=["revenue", "ebitda", "cash_balance"],
    )
    assert status == "red"


def test_no_updates_ever_is_amber(scorer):
    """Company with no updates at all → amber."""
    company = Company(
        id="test-2",
        fund_id="fund-1",
        name="NewCo",
        canonical_metrics=DEFAULT_PE_METRICS,
        last_update_at=None,
    )
    status, reasons = scorer.score(company)
    assert status == "amber"
    assert any("no updates" in r.lower() for r in reasons)
