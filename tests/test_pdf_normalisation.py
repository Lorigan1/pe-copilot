"""Integration test: PDF file → normalisation pipeline → validated output.

Mocks the LLM and cloud services to test the full pipeline path for PDF files.
Uses Helix Manufacturing (quarterly board pack) as the reference case.
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.models.company import Company
from app.models.metric_schema import DEFAULT_PE_METRICS, MetricDefinition
from app.models.update import ProcessingStatus, SourceFileType, SourceType, Update
from app.services.normaliser import NormaliserService

TESTDATA = Path(__file__).parent.parent / "testdata"


# ─── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def helix_pdf_bytes():
    return (TESTDATA / "Helix_Manufacturing_Q4_2025.pdf").read_bytes()


@pytest.fixture
def helix_company():
    """Helix Manufacturing company entity as it exists in Firestore."""
    return Company(
        id="hLoHWgzh9C2oJ0Fngc2S",
        fund_id="pOQXLN0E1V1clZcSDYcT",
        name="Helix Manufacturing",
        sector="Manufacturing",
        primary_contact_name="Tom Richardson",
        primary_contact_email="tom@helix.example.com",
        canonical_metrics=DEFAULT_PE_METRICS + [
            MetricDefinition(
                name="units_produced",
                label="Units Produced",
                type="number",
                unit="units",
                category="operational",
                is_required=False,
                variance_threshold=0.15,
            ),
        ],
        mapping_instructions=(
            "Helix sends a PDF board pack. Financial data is in tables on pages 3-5. "
            "Revenue is 'Turnover'. Cash balance is 'Bank & Cash'. "
            "They also report 'Units Produced' which maps to our operational KPI."
        ),
        reporting_frequency="quarterly",
        accounting_system="QuickBooks",
    )


@pytest.fixture
def pdf_update():
    """A pending update record for a PDF upload."""
    return Update(
        id="test-pdf-update-001",
        fund_id="pOQXLN0E1V1clZcSDYcT",
        company_id="hLoHWgzh9C2oJ0Fngc2S",
        source_type=SourceType.MANUAL_UPLOAD,
        source_file_type=SourceFileType.PDF,
        raw_file_urls=["gs://pe-copilot-dev-raw-uploads/test/Helix_Manufacturing_Q4_2025.pdf"],
        metrics_period="Q4 2025",
        processing_status=ProcessingStatus.PENDING,
    )


@pytest.fixture
def mock_llm_normalisation_response():
    """Realistic LLM normalisation response for Helix's Q4 2025 data."""
    return {
        "period": "Q4 2025",
        "metrics": {
            "revenue": 3200000.0,
            "gross_profit": 1344000.0,
            "ebitda": 520000.0,
            "net_income": 380000.0,
            "cash_balance": 890000.0,
            "total_debt": 1800000.0,
            "net_assets": 2290000.0,
            "headcount": 142,
            "units_produced": 45200,
        },
        "unmapped_data": [
            "Defect Rate: 1.2%",
            "On-Time Delivery: 96.4%",
            "Average Order Value: £8,450",
            "Capacity Utilisation: 87%",
        ],
        "confidence": 0.92,
        "notes": (
            "Revenue mapped from 'Turnover'. Cash balance mapped from 'Bank & Cash'. "
            "Total debt calculated as Term Loan (£1,200,000) + Overdraft Facility (£600,000) = £1,800,000. "
            "Operating cash flow not explicitly stated but commentary mentions healthy cash position."
        ),
    }


@pytest.fixture
def mock_llm_normalisation_with_previous():
    """Same response but for variance testing with Q3 data available."""
    return {
        "period": "Q4 2025",
        "metrics": {
            "revenue": 3200000.0,
            "gross_profit": 1344000.0,
            "ebitda": 520000.0,
            "net_income": 380000.0,
            "cash_balance": 890000.0,
            "total_debt": 1800000.0,
            "net_assets": 2290000.0,
            "headcount": 142,
            "units_produced": 45200,
        },
        "unmapped_data": [],
        "confidence": 0.92,
        "notes": "Mapped from board pack tables.",
    }


@pytest.fixture
def mock_llm_summary_response():
    return {
        "summary": (
            "Helix Manufacturing reported strong Q4 2025 results with turnover of £3.2M (+8.1% QoQ). "
            "EBITDA of £520K (16.3% margin) beat budget. Production output reached a record 45,200 units. "
            "Cash position of £890K is healthy but £400K capex planned for Q1 2026 line 4 expansion."
        ),
        "risks": [
            "Midlands facility lease renewal due Q1 2026 — expecting 12-15% rent increase",
            "Capex programme for line 4 will draw down £400K, significantly reducing cash reserves",
            "Operating cash flow not explicitly reported in the board pack",
        ],
        "action_items": [
            "Request operating cash flow statement from Helix",
            "Monitor Midlands lease negotiation outcome",
            "Review line 4 capex budget vs actual spend in Q1 2026",
        ],
    }


@pytest.fixture
def q3_previous_update():
    """A completed Q3 2025 update (for variance testing)."""
    return Update(
        id="test-pdf-update-q3",
        fund_id="pOQXLN0E1V1clZcSDYcT",
        company_id="hLoHWgzh9C2oJ0Fngc2S",
        source_type=SourceType.MANUAL_UPLOAD,
        source_file_type=SourceFileType.PDF,
        raw_file_urls=[],
        metrics_period="Q3 2025",
        processing_status=ProcessingStatus.COMPLETED,
        normalised_metrics={
            "revenue": 2960000.0,
            "gross_profit": 1213600.0,
            "ebitda": 420200.0,
            "net_income": 297760.0,
            "cash_balance": 780000.0,
            "total_debt": 1900000.0,
            "net_assets": 1970000.0,
            "headcount": 137,
            "units_produced": 41800,
        },
    )


# ─── Tests ───────────────────────────────────────────────────────


class TestPDFNormalisationPipeline:
    """End-to-end pipeline test for PDF → normalised metrics."""

    @pytest.mark.asyncio
    async def test_full_pipeline_produces_completed_update(
        self,
        helix_pdf_bytes,
        helix_company,
        pdf_update,
        mock_llm_normalisation_response,
        mock_llm_summary_response,
    ):
        normaliser = NormaliserService()

        with (
            patch("app.services.normaliser.storage_service") as mock_storage,
            patch("app.services.normaliser.firestore_service") as mock_firestore,
            patch("app.services.normaliser.llm_service") as mock_llm,
        ):
            mock_storage.download_file = AsyncMock(return_value=helix_pdf_bytes)
            mock_firestore.save_update = AsyncMock()
            mock_firestore.get_company = AsyncMock(return_value=helix_company)
            mock_firestore.get_previous_update = AsyncMock(return_value=None)
            mock_firestore.update_company = AsyncMock()
            mock_llm.call_json = AsyncMock(
                side_effect=[mock_llm_normalisation_response, mock_llm_summary_response]
            )

            result = await normaliser.process_update(pdf_update)

        assert result.processing_status == ProcessingStatus.COMPLETED
        assert result.llm_confidence == 0.92
        assert result.processed_at is not None

    @pytest.mark.asyncio
    async def test_extracted_text_contains_table_data(
        self,
        helix_pdf_bytes,
        helix_company,
        pdf_update,
        mock_llm_normalisation_response,
        mock_llm_summary_response,
    ):
        normaliser = NormaliserService()

        with (
            patch("app.services.normaliser.storage_service") as mock_storage,
            patch("app.services.normaliser.firestore_service") as mock_firestore,
            patch("app.services.normaliser.llm_service") as mock_llm,
        ):
            mock_storage.download_file = AsyncMock(return_value=helix_pdf_bytes)
            mock_firestore.save_update = AsyncMock()
            mock_firestore.get_company = AsyncMock(return_value=helix_company)
            mock_firestore.get_previous_update = AsyncMock(return_value=None)
            mock_firestore.update_company = AsyncMock()
            mock_llm.call_json = AsyncMock(
                side_effect=[mock_llm_normalisation_response, mock_llm_summary_response]
            )

            result = await normaliser.process_update(pdf_update)

        # Extracted text should contain Helix's specific labels
        assert "Turnover" in result.extracted_text
        assert "3,200,000" in result.extracted_text
        assert "Units Produced" in result.extracted_text

    @pytest.mark.asyncio
    async def test_normalised_metrics_include_custom_kpi(
        self,
        helix_pdf_bytes,
        helix_company,
        pdf_update,
        mock_llm_normalisation_response,
        mock_llm_summary_response,
    ):
        """Helix has a custom 'units_produced' metric beyond the defaults."""
        normaliser = NormaliserService()

        with (
            patch("app.services.normaliser.storage_service") as mock_storage,
            patch("app.services.normaliser.firestore_service") as mock_firestore,
            patch("app.services.normaliser.llm_service") as mock_llm,
        ):
            mock_storage.download_file = AsyncMock(return_value=helix_pdf_bytes)
            mock_firestore.save_update = AsyncMock()
            mock_firestore.get_company = AsyncMock(return_value=helix_company)
            mock_firestore.get_previous_update = AsyncMock(return_value=None)
            mock_firestore.update_company = AsyncMock()
            mock_llm.call_json = AsyncMock(
                side_effect=[mock_llm_normalisation_response, mock_llm_summary_response]
            )

            result = await normaliser.process_update(pdf_update)

        assert result.normalised_metrics["revenue"] == 3200000.0
        assert result.normalised_metrics["ebitda"] == 520000.0
        assert result.normalised_metrics["units_produced"] == 45200
        assert result.normalised_metrics["total_debt"] == 1800000.0

    @pytest.mark.asyncio
    async def test_missing_operating_cashflow_detected(
        self,
        helix_pdf_bytes,
        helix_company,
        pdf_update,
        mock_llm_normalisation_response,
        mock_llm_summary_response,
    ):
        """Operating cash flow isn't in the board pack — should be flagged."""
        normaliser = NormaliserService()

        with (
            patch("app.services.normaliser.storage_service") as mock_storage,
            patch("app.services.normaliser.firestore_service") as mock_firestore,
            patch("app.services.normaliser.llm_service") as mock_llm,
        ):
            mock_storage.download_file = AsyncMock(return_value=helix_pdf_bytes)
            mock_firestore.save_update = AsyncMock()
            mock_firestore.get_company = AsyncMock(return_value=helix_company)
            mock_firestore.get_previous_update = AsyncMock(return_value=None)
            mock_firestore.update_company = AsyncMock()
            mock_llm.call_json = AsyncMock(
                side_effect=[mock_llm_normalisation_response, mock_llm_summary_response]
            )

            result = await normaliser.process_update(pdf_update)

        assert "operating_cashflow" in result.missing_metrics

    @pytest.mark.asyncio
    async def test_variance_calculation_with_previous_quarter(
        self,
        helix_pdf_bytes,
        helix_company,
        pdf_update,
        mock_llm_normalisation_with_previous,
        mock_llm_summary_response,
        q3_previous_update,
    ):
        """When Q3 data exists, variances should be calculated."""
        normaliser = NormaliserService()

        with (
            patch("app.services.normaliser.storage_service") as mock_storage,
            patch("app.services.normaliser.firestore_service") as mock_firestore,
            patch("app.services.normaliser.llm_service") as mock_llm,
        ):
            mock_storage.download_file = AsyncMock(return_value=helix_pdf_bytes)
            mock_firestore.save_update = AsyncMock()
            mock_firestore.get_company = AsyncMock(return_value=helix_company)
            mock_firestore.get_previous_update = AsyncMock(return_value=q3_previous_update)
            mock_firestore.update_company = AsyncMock()
            mock_llm.call_json = AsyncMock(
                side_effect=[mock_llm_normalisation_with_previous, mock_llm_summary_response]
            )

            result = await normaliser.process_update(pdf_update)

        # Revenue variance: (3.2M - 2.96M) / 2.96M ≈ 0.0811
        assert "revenue" in result.variances
        assert 0.07 < result.variances["revenue"] < 0.09

        # EBITDA variance: (520K - 420.2K) / 420.2K ≈ 0.2375
        assert "ebitda" in result.variances
        assert 0.22 < result.variances["ebitda"] < 0.25

        # Units produced variance: (45200 - 41800) / 41800 ≈ 0.0813
        assert "units_produced" in result.variances
        assert 0.07 < result.variances["units_produced"] < 0.09

    @pytest.mark.asyncio
    async def test_summary_captures_risks(
        self,
        helix_pdf_bytes,
        helix_company,
        pdf_update,
        mock_llm_normalisation_response,
        mock_llm_summary_response,
    ):
        normaliser = NormaliserService()

        with (
            patch("app.services.normaliser.storage_service") as mock_storage,
            patch("app.services.normaliser.firestore_service") as mock_firestore,
            patch("app.services.normaliser.llm_service") as mock_llm,
        ):
            mock_storage.download_file = AsyncMock(return_value=helix_pdf_bytes)
            mock_firestore.save_update = AsyncMock()
            mock_firestore.get_company = AsyncMock(return_value=helix_company)
            mock_firestore.get_previous_update = AsyncMock(return_value=None)
            mock_firestore.update_company = AsyncMock()
            mock_llm.call_json = AsyncMock(
                side_effect=[mock_llm_normalisation_response, mock_llm_summary_response]
            )

            result = await normaliser.process_update(pdf_update)

        assert "Helix" in result.llm_summary
        assert len(result.llm_risks) == 3
        assert any("lease" in r.lower() for r in result.llm_risks)
        assert len(result.llm_action_items) == 3

    @pytest.mark.asyncio
    async def test_llm_receives_helix_mapping_instructions(
        self,
        helix_pdf_bytes,
        helix_company,
        pdf_update,
        mock_llm_normalisation_response,
        mock_llm_summary_response,
    ):
        """The LLM prompt should include Helix's mapping instructions."""
        normaliser = NormaliserService()

        with (
            patch("app.services.normaliser.storage_service") as mock_storage,
            patch("app.services.normaliser.firestore_service") as mock_firestore,
            patch("app.services.normaliser.llm_service") as mock_llm,
        ):
            mock_storage.download_file = AsyncMock(return_value=helix_pdf_bytes)
            mock_firestore.save_update = AsyncMock()
            mock_firestore.get_company = AsyncMock(return_value=helix_company)
            mock_firestore.get_previous_update = AsyncMock(return_value=None)
            mock_firestore.update_company = AsyncMock()
            mock_llm.call_json = AsyncMock(
                side_effect=[mock_llm_normalisation_response, mock_llm_summary_response]
            )

            await normaliser.process_update(pdf_update)

        # Check normalisation call includes mapping instructions
        normalisation_call = mock_llm.call_json.call_args_list[0]
        user_prompt = normalisation_call.kwargs.get("user_prompt", "")
        assert "Turnover" in user_prompt or "Bank & Cash" in user_prompt or "Units Produced" in user_prompt
