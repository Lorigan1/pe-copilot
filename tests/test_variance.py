"""Tests for MoM variance calculation.

Verifies that when a second period is processed for the same company,
the pipeline correctly calculates percentage changes against the prior period.
Uses NorthStar Logistics Jan → Feb 2026 as the reference case.
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.models.company import Company
from app.models.metric_schema import DEFAULT_PE_METRICS
from app.models.update import ProcessingStatus, SourceFileType, SourceType, Update
from app.services.normaliser import NormaliserService

TESTDATA = Path(__file__).parent.parent / "testdata"


# ─── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def northstar_feb_bytes():
    return (TESTDATA / "NorthStar_Logistics_Feb2026.xlsx").read_bytes()


@pytest.fixture
def northstar_company():
    return Company(
        id="1jstxqLHoqLKtetqNUWP",
        fund_id="pOQXLN0E1V1clZcSDYcT",
        name="NorthStar Logistics",
        sector="Logistics & Distribution",
        primary_contact_name="James Chen",
        primary_contact_email="james.chen@northstar.example.com",
        canonical_metrics=DEFAULT_PE_METRICS,
        mapping_instructions=(
            "NorthStar uses Sage. Their management pack has tabs: 'P&L Summary', "
            "'Balance Sheet', 'Cash Flow'. Revenue is labelled 'Net Sales'. "
            "EBITDA is labelled 'Operating Profit Before D&A'."
        ),
        reporting_frequency="monthly",
        accounting_system="Sage",
    )


@pytest.fixture
def feb_update():
    return Update(
        id="test-feb-update-001",
        fund_id="pOQXLN0E1V1clZcSDYcT",
        company_id="1jstxqLHoqLKtetqNUWP",
        source_type=SourceType.MANUAL_UPLOAD,
        source_file_type=SourceFileType.EXCEL,
        raw_file_urls=["gs://pe-copilot-dev-raw-uploads/test/NorthStar_Feb2026.xlsx"],
        metrics_period="Feb 2026",
        processing_status=ProcessingStatus.PENDING,
    )


@pytest.fixture
def jan_completed_update():
    """The completed Jan 2026 update with normalised metrics (simulates what's in Firestore)."""
    return Update(
        id="test-jan-update-001",
        fund_id="pOQXLN0E1V1clZcSDYcT",
        company_id="1jstxqLHoqLKtetqNUWP",
        source_type=SourceType.MANUAL_UPLOAD,
        source_file_type=SourceFileType.EXCEL,
        raw_file_urls=[],
        metrics_period="Jan 2026",
        processing_status=ProcessingStatus.COMPLETED,
        normalised_metrics={
            "revenue": 2450000.0,
            "gross_profit": 735000.0,
            "ebitda": -147000.0,  # Will use a more realistic number below
            "net_income": 97125.0,
            "cash_balance": 892300.0,
            "total_debt": 710500.0,
            "net_assets": 4133800.0,
            "operating_cashflow": 98125.0,
            "headcount": 187,
        },
    )


@pytest.fixture
def feb_normalisation_response():
    """What Claude would return for Feb 2026 NorthStar data."""
    return {
        "period": "Feb 2026",
        "metrics": {
            "revenue": 2609250.0,
            "gross_profit": 757250.0,
            "ebitda": -172200.0,
            "net_income": 79825.0,
            "cash_balance": 820500.0,
            "total_debt": 740000.0,
            "net_assets": 4015500.0,
            "operating_cashflow": 41625.0,
            "headcount": 190,
        },
        "unmapped_data": [
            "Fleet Operating Costs: £149,450 (+22% MoM — fuel spike)",
            "Professional Fees: £9,800 (-60% MoM — Jan was one-off)",
            "On-Time Delivery: 91.8% (down from 94.6%)",
        ],
        "confidence": 0.90,
        "notes": (
            "Revenue mapped from 'Net Sales'. EBITDA mapped from 'Operating Profit Before D&A'. "
            "Fleet costs spiked 22% MoM which is notable. Professional fees dropped 60% suggesting "
            "Jan included one-off legal costs."
        ),
    }


@pytest.fixture
def feb_summary_response():
    return {
        "summary": (
            "NorthStar Logistics grew revenue 6.5% MoM to £2.61M in Feb 2026, driven by new "
            "contract wins. However, gross margin compressed to 29.0% (from 30.0%) as cost of sales "
            "rose 8.0% — faster than revenue growth. Fleet costs spiked 22% due to fuel price increases "
            "and unplanned maintenance, signalling operational strain. Cash declined 8% to £820.5K."
        ),
        "risks": [
            "Fleet operating costs surged 22% MoM — investigate fuel hedging and maintenance scheduling",
            "Gross margin compression (30.0% → 29.0%) despite revenue growth suggests cost control issues",
            "On-time delivery declined to 91.8% from 94.6% — capacity strain from new contracts",
            "Cash balance declined 8% to £820.5K — monitor working capital adequacy",
        ],
        "action_items": [
            "Request fleet cost breakdown: separate fuel vs maintenance to identify root cause of 22% spike",
            "Review new contract terms to confirm pricing covers incremental distribution costs",
            "Assess fleet capacity — may need additional vehicles if on-time delivery continues declining",
            "Obtain 3-month cash forecast to assess liquidity runway given declining cash position",
        ],
    }


# ─── Variance calculation unit tests ────────────────────────────


class TestVarianceCalculation:
    """Test the _calculate_variances method directly."""

    def test_basic_variance(self):
        normaliser = NormaliserService()
        current = {"revenue": 1100.0, "ebitda": 200.0}
        previous = {"revenue": 1000.0, "ebitda": 250.0}
        result = normaliser._calculate_variances(current, previous)

        assert abs(result["revenue"] - 0.1) < 0.001  # +10%
        assert abs(result["ebitda"] - (-0.2)) < 0.001  # -20%

    def test_missing_previous_metric_skipped(self):
        normaliser = NormaliserService()
        current = {"revenue": 1000.0, "new_metric": 500.0}
        previous = {"revenue": 900.0}
        result = normaliser._calculate_variances(current, previous)

        assert "revenue" in result
        assert "new_metric" not in result  # No previous to compare

    def test_zero_previous_skipped(self):
        normaliser = NormaliserService()
        current = {"revenue": 1000.0}
        previous = {"revenue": 0}
        result = normaliser._calculate_variances(current, previous)

        assert "revenue" not in result  # Division by zero avoided

    def test_none_values_skipped(self):
        normaliser = NormaliserService()
        current = {"revenue": None, "ebitda": 200.0}
        previous = {"revenue": 1000.0, "ebitda": 180.0}
        result = normaliser._calculate_variances(current, previous)

        assert "revenue" not in result
        assert "ebitda" in result

    def test_large_positive_variance(self):
        normaliser = NormaliserService()
        current = {"revenue": 2000.0}
        previous = {"revenue": 1000.0}
        result = normaliser._calculate_variances(current, previous)

        assert abs(result["revenue"] - 1.0) < 0.001  # +100%

    def test_negative_to_less_negative(self):
        """Common for metrics like net debt."""
        normaliser = NormaliserService()
        current = {"net_debt": -500.0}
        previous = {"net_debt": -1000.0}
        result = normaliser._calculate_variances(current, previous)

        # (-500 - (-1000)) / |-1000| = 0.5
        assert abs(result["net_debt"] - 0.5) < 0.001


# ─── Integration: variance in full pipeline ─────────────────────


class TestVariancePipeline:
    """End-to-end variance calculation when processing a second period."""

    @pytest.mark.asyncio
    async def test_variances_populated_with_previous_period(
        self,
        northstar_feb_bytes,
        northstar_company,
        feb_update,
        jan_completed_update,
        feb_normalisation_response,
        feb_summary_response,
    ):
        normaliser = NormaliserService()

        with (
            patch("app.services.normaliser.storage_service") as mock_storage,
            patch("app.services.normaliser.firestore_service") as mock_firestore,
            patch("app.services.normaliser.llm_service") as mock_llm,
        ):
            mock_storage.download_file = AsyncMock(return_value=northstar_feb_bytes)
            mock_firestore.save_update = AsyncMock()
            mock_firestore.get_company = AsyncMock(return_value=northstar_company)
            mock_firestore.get_previous_update = AsyncMock(return_value=jan_completed_update)
            mock_firestore.update_company = AsyncMock()
            mock_llm.call_json = AsyncMock(
                side_effect=[feb_normalisation_response, feb_summary_response]
            )

            result = await normaliser.process_update(feb_update)

        assert result.processing_status == ProcessingStatus.COMPLETED
        assert len(result.variances) > 0

    @pytest.mark.asyncio
    async def test_revenue_variance_is_positive(
        self,
        northstar_feb_bytes,
        northstar_company,
        feb_update,
        jan_completed_update,
        feb_normalisation_response,
        feb_summary_response,
    ):
        """Revenue went from 2.45M → 2.61M, should be ~+6.5%."""
        normaliser = NormaliserService()

        with (
            patch("app.services.normaliser.storage_service") as mock_storage,
            patch("app.services.normaliser.firestore_service") as mock_firestore,
            patch("app.services.normaliser.llm_service") as mock_llm,
        ):
            mock_storage.download_file = AsyncMock(return_value=northstar_feb_bytes)
            mock_firestore.save_update = AsyncMock()
            mock_firestore.get_company = AsyncMock(return_value=northstar_company)
            mock_firestore.get_previous_update = AsyncMock(return_value=jan_completed_update)
            mock_firestore.update_company = AsyncMock()
            mock_llm.call_json = AsyncMock(
                side_effect=[feb_normalisation_response, feb_summary_response]
            )

            result = await normaliser.process_update(feb_update)

        assert "revenue" in result.variances
        # (2609250 - 2450000) / 2450000 ≈ 0.065
        assert 0.06 < result.variances["revenue"] < 0.07

    @pytest.mark.asyncio
    async def test_cash_variance_is_negative(
        self,
        northstar_feb_bytes,
        northstar_company,
        feb_update,
        jan_completed_update,
        feb_normalisation_response,
        feb_summary_response,
    ):
        """Cash went from 892.3K → 820.5K, should be ~-8%."""
        normaliser = NormaliserService()

        with (
            patch("app.services.normaliser.storage_service") as mock_storage,
            patch("app.services.normaliser.firestore_service") as mock_firestore,
            patch("app.services.normaliser.llm_service") as mock_llm,
        ):
            mock_storage.download_file = AsyncMock(return_value=northstar_feb_bytes)
            mock_firestore.save_update = AsyncMock()
            mock_firestore.get_company = AsyncMock(return_value=northstar_company)
            mock_firestore.get_previous_update = AsyncMock(return_value=jan_completed_update)
            mock_firestore.update_company = AsyncMock()
            mock_llm.call_json = AsyncMock(
                side_effect=[feb_normalisation_response, feb_summary_response]
            )

            result = await normaliser.process_update(feb_update)

        assert "cash_balance" in result.variances
        assert result.variances["cash_balance"] < 0  # Cash declined

    @pytest.mark.asyncio
    async def test_no_variances_without_previous(
        self,
        northstar_feb_bytes,
        northstar_company,
        feb_update,
        feb_normalisation_response,
        feb_summary_response,
    ):
        """First upload for a company should have no variances."""
        normaliser = NormaliserService()

        with (
            patch("app.services.normaliser.storage_service") as mock_storage,
            patch("app.services.normaliser.firestore_service") as mock_firestore,
            patch("app.services.normaliser.llm_service") as mock_llm,
        ):
            mock_storage.download_file = AsyncMock(return_value=northstar_feb_bytes)
            mock_firestore.save_update = AsyncMock()
            mock_firestore.get_company = AsyncMock(return_value=northstar_company)
            mock_firestore.get_previous_update = AsyncMock(return_value=None)  # No previous
            mock_firestore.update_company = AsyncMock()
            mock_llm.call_json = AsyncMock(
                side_effect=[feb_normalisation_response, feb_summary_response]
            )

            result = await normaliser.process_update(feb_update)

        assert result.variances == {}

    @pytest.mark.asyncio
    async def test_summarisation_receives_variances(
        self,
        northstar_feb_bytes,
        northstar_company,
        feb_update,
        jan_completed_update,
        feb_normalisation_response,
        feb_summary_response,
    ):
        """The summarisation prompt should include variance data for context."""
        normaliser = NormaliserService()

        with (
            patch("app.services.normaliser.storage_service") as mock_storage,
            patch("app.services.normaliser.firestore_service") as mock_firestore,
            patch("app.services.normaliser.llm_service") as mock_llm,
        ):
            mock_storage.download_file = AsyncMock(return_value=northstar_feb_bytes)
            mock_firestore.save_update = AsyncMock()
            mock_firestore.get_company = AsyncMock(return_value=northstar_company)
            mock_firestore.get_previous_update = AsyncMock(return_value=jan_completed_update)
            mock_firestore.update_company = AsyncMock()
            mock_llm.call_json = AsyncMock(
                side_effect=[feb_normalisation_response, feb_summary_response]
            )

            await normaliser.process_update(feb_update)

        # Second LLM call is summarisation — should include previous metrics
        summary_call = mock_llm.call_json.call_args_list[1]
        user_prompt = summary_call.kwargs.get("user_prompt", "")
        assert "2450000" in user_prompt or "PREVIOUS" in user_prompt.upper()
