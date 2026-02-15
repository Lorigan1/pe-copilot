"""Integration test: CSV file → normalisation pipeline → validated output.

Mocks the LLM and cloud services to test the full pipeline path for CSV files
without hitting external APIs. Verifies that:
1. CSV bytes are correctly parsed (Layer 1)
2. The extracted text is sent to the LLM with proper context (Layer 2)
3. The LLM response is validated and stored correctly (Layer 3)
"""

import json
from datetime import datetime
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
def brightpath_csv_bytes():
    return (TESTDATA / "BrightPath_Education_Jan2026.csv").read_bytes()


@pytest.fixture
def brightpath_company():
    """BrightPath Education company entity as it exists in Firestore."""
    return Company(
        id="CxsMSU8KTbmuY4sXGAlY",
        fund_id="pOQXLN0E1V1clZcSDYcT",
        name="BrightPath Education",
        sector="Education & Training",
        primary_contact_name="Priya Sharma",
        primary_contact_email="priya@brightpath.example.com",
        canonical_metrics=DEFAULT_PE_METRICS,
        mapping_instructions=(
            "BrightPath exports from Xero as CSV. Flat file format. "
            "Revenue is 'Total Income'. They don't separate EBITDA — "
            "calculate from 'Total Income' minus 'Total Expenses' plus 'Depreciation'."
        ),
        reporting_frequency="monthly",
        accounting_system="Xero",
    )


@pytest.fixture
def csv_update():
    """A pending update record for a CSV upload."""
    return Update(
        id="test-csv-update-001",
        fund_id="pOQXLN0E1V1clZcSDYcT",
        company_id="CxsMSU8KTbmuY4sXGAlY",
        source_type=SourceType.MANUAL_UPLOAD,
        source_file_type=SourceFileType.CSV,
        raw_file_urls=["gs://pe-copilot-dev-raw-uploads/test/BrightPath_Education_Jan2026.csv"],
        metrics_period="Jan 2026",
        processing_status=ProcessingStatus.PENDING,
    )


@pytest.fixture
def mock_llm_normalisation_response():
    """Realistic LLM normalisation response for BrightPath's Jan 2026 data."""
    return {
        "period": "Jan 2026",
        "metrics": {
            "revenue": 875000.0,
            "gross_profit": 437500.0,
            "ebitda": 148750.0,  # Total Income(875k) - Total Expenses(306.25k) + Depreciation(17.5k) ≈ doesn't add up exactly, but LLM calculated
            "net_income": 131250.0,
            "cash_balance": 520000.0,
            "total_debt": 1100000.0,
            "net_assets": 1850000.0,
            "headcount": 78,
        },
        "unmapped_data": [
            "Course Fees: 620000",
            "Corporate Training Contracts: 180000",
            "Government Grants: 50000",
        ],
        "confidence": 0.88,
        "notes": (
            "EBITDA calculated as Total Income (875,000) minus Total Expenses (306,250) "
            "plus Depreciation (17,500) = 586,250. However, this seems high — may need to use "
            "Net Profit (131,250) + Depreciation (17,500) = 148,750 as a more standard calculation. "
            "Used the latter approach. Operating cash flow not explicitly reported."
        ),
    }


@pytest.fixture
def mock_llm_summary_response():
    return {
        "summary": (
            "BrightPath Education generated £875k revenue in Jan 2026, with £437.5k gross profit (50% margin). "
            "Net income of £131.25k is healthy. Cash position of £520k against £1.1M debt gives adequate liquidity. "
            "Headcount at 78 suggests stable operations."
        ),
        "risks": [
            "Operating cash flow not reported — liquidity position may be incomplete",
            "Government grants (£50k) may be non-recurring, creating revenue concentration risk",
        ],
        "action_items": [
            "Request operating cash flow statement from BrightPath",
            "Confirm whether government grants are recurring or one-off",
            "Verify EBITDA calculation methodology with BrightPath CFO",
        ],
    }


# ─── Tests ───────────────────────────────────────────────────────


class TestCSVNormalisationPipeline:
    """End-to-end pipeline test for CSV → normalised metrics."""

    @pytest.mark.asyncio
    async def test_full_pipeline_produces_completed_update(
        self,
        brightpath_csv_bytes,
        brightpath_company,
        csv_update,
        mock_llm_normalisation_response,
        mock_llm_summary_response,
    ):
        """The pipeline should go from pending → completed for a valid CSV."""
        normaliser = NormaliserService()

        with (
            patch("app.services.normaliser.storage_service") as mock_storage,
            patch("app.services.normaliser.firestore_service") as mock_firestore,
            patch("app.services.normaliser.llm_service") as mock_llm,
        ):
            # Mock cloud services
            mock_storage.download_file = AsyncMock(return_value=brightpath_csv_bytes)
            mock_firestore.save_update = AsyncMock()
            mock_firestore.get_company = AsyncMock(return_value=brightpath_company)
            mock_firestore.get_previous_update = AsyncMock(return_value=None)
            mock_firestore.update_company = AsyncMock()

            # Mock LLM: first call = normalisation, second call = summary
            mock_llm.call_json = AsyncMock(
                side_effect=[mock_llm_normalisation_response, mock_llm_summary_response]
            )

            result = await normaliser.process_update(csv_update)

        assert result.processing_status == ProcessingStatus.COMPLETED
        assert result.llm_confidence == 0.88
        assert result.processed_at is not None

    @pytest.mark.asyncio
    async def test_extracted_text_contains_csv_data(
        self,
        brightpath_csv_bytes,
        brightpath_company,
        csv_update,
        mock_llm_normalisation_response,
        mock_llm_summary_response,
    ):
        """Layer 1 should produce extracted text that includes key BrightPath data."""
        normaliser = NormaliserService()

        with (
            patch("app.services.normaliser.storage_service") as mock_storage,
            patch("app.services.normaliser.firestore_service") as mock_firestore,
            patch("app.services.normaliser.llm_service") as mock_llm,
        ):
            mock_storage.download_file = AsyncMock(return_value=brightpath_csv_bytes)
            mock_firestore.save_update = AsyncMock()
            mock_firestore.get_company = AsyncMock(return_value=brightpath_company)
            mock_firestore.get_previous_update = AsyncMock(return_value=None)
            mock_firestore.update_company = AsyncMock()
            mock_llm.call_json = AsyncMock(
                side_effect=[mock_llm_normalisation_response, mock_llm_summary_response]
            )

            result = await normaliser.process_update(csv_update)

        # The extracted text should contain BrightPath's Xero labels
        assert "Total Income" in result.extracted_text
        assert "875000" in result.extracted_text
        assert "Depreciation" in result.extracted_text

    @pytest.mark.asyncio
    async def test_normalised_metrics_populated(
        self,
        brightpath_csv_bytes,
        brightpath_company,
        csv_update,
        mock_llm_normalisation_response,
        mock_llm_summary_response,
    ):
        """The normalised metrics should be populated from the LLM response."""
        normaliser = NormaliserService()

        with (
            patch("app.services.normaliser.storage_service") as mock_storage,
            patch("app.services.normaliser.firestore_service") as mock_firestore,
            patch("app.services.normaliser.llm_service") as mock_llm,
        ):
            mock_storage.download_file = AsyncMock(return_value=brightpath_csv_bytes)
            mock_firestore.save_update = AsyncMock()
            mock_firestore.get_company = AsyncMock(return_value=brightpath_company)
            mock_firestore.get_previous_update = AsyncMock(return_value=None)
            mock_firestore.update_company = AsyncMock()
            mock_llm.call_json = AsyncMock(
                side_effect=[mock_llm_normalisation_response, mock_llm_summary_response]
            )

            result = await normaliser.process_update(csv_update)

        assert result.normalised_metrics["revenue"] == 875000.0
        assert result.normalised_metrics["ebitda"] == 148750.0
        assert result.normalised_metrics["net_income"] == 131250.0
        assert result.normalised_metrics["cash_balance"] == 520000.0
        assert result.normalised_metrics["headcount"] == 78

    @pytest.mark.asyncio
    async def test_missing_operating_cashflow_detected(
        self,
        brightpath_csv_bytes,
        brightpath_company,
        csv_update,
        mock_llm_normalisation_response,
        mock_llm_summary_response,
    ):
        """Operating cash flow is missing from the CSV — should be flagged."""
        normaliser = NormaliserService()

        with (
            patch("app.services.normaliser.storage_service") as mock_storage,
            patch("app.services.normaliser.firestore_service") as mock_firestore,
            patch("app.services.normaliser.llm_service") as mock_llm,
        ):
            mock_storage.download_file = AsyncMock(return_value=brightpath_csv_bytes)
            mock_firestore.save_update = AsyncMock()
            mock_firestore.get_company = AsyncMock(return_value=brightpath_company)
            mock_firestore.get_previous_update = AsyncMock(return_value=None)
            mock_firestore.update_company = AsyncMock()
            mock_llm.call_json = AsyncMock(
                side_effect=[mock_llm_normalisation_response, mock_llm_summary_response]
            )

            result = await normaliser.process_update(csv_update)

        assert "operating_cashflow" in result.missing_metrics

    @pytest.mark.asyncio
    async def test_summary_and_risks_populated(
        self,
        brightpath_csv_bytes,
        brightpath_company,
        csv_update,
        mock_llm_normalisation_response,
        mock_llm_summary_response,
    ):
        """Summary, risks, and action items should come through from the LLM."""
        normaliser = NormaliserService()

        with (
            patch("app.services.normaliser.storage_service") as mock_storage,
            patch("app.services.normaliser.firestore_service") as mock_firestore,
            patch("app.services.normaliser.llm_service") as mock_llm,
        ):
            mock_storage.download_file = AsyncMock(return_value=brightpath_csv_bytes)
            mock_firestore.save_update = AsyncMock()
            mock_firestore.get_company = AsyncMock(return_value=brightpath_company)
            mock_firestore.get_previous_update = AsyncMock(return_value=None)
            mock_firestore.update_company = AsyncMock()
            mock_llm.call_json = AsyncMock(
                side_effect=[mock_llm_normalisation_response, mock_llm_summary_response]
            )

            result = await normaliser.process_update(csv_update)

        assert "BrightPath" in result.llm_summary
        assert len(result.llm_risks) == 2
        assert len(result.llm_action_items) == 3

    @pytest.mark.asyncio
    async def test_llm_receives_mapping_instructions(
        self,
        brightpath_csv_bytes,
        brightpath_company,
        csv_update,
        mock_llm_normalisation_response,
        mock_llm_summary_response,
    ):
        """The LLM should receive BrightPath's mapping instructions in the prompt."""
        normaliser = NormaliserService()

        with (
            patch("app.services.normaliser.storage_service") as mock_storage,
            patch("app.services.normaliser.firestore_service") as mock_firestore,
            patch("app.services.normaliser.llm_service") as mock_llm,
        ):
            mock_storage.download_file = AsyncMock(return_value=brightpath_csv_bytes)
            mock_firestore.save_update = AsyncMock()
            mock_firestore.get_company = AsyncMock(return_value=brightpath_company)
            mock_firestore.get_previous_update = AsyncMock(return_value=None)
            mock_firestore.update_company = AsyncMock()
            mock_llm.call_json = AsyncMock(
                side_effect=[mock_llm_normalisation_response, mock_llm_summary_response]
            )

            await normaliser.process_update(csv_update)

        # Check the normalisation call (first call)
        normalisation_call = mock_llm.call_json.call_args_list[0]
        user_prompt = normalisation_call.kwargs.get("user_prompt", normalisation_call[1].get("user_prompt", ""))
        if not user_prompt:
            # Try positional args
            user_prompt = str(normalisation_call)

        assert "Total Income" in user_prompt or "Xero" in user_prompt

    @pytest.mark.asyncio
    async def test_low_confidence_triggers_needs_review(
        self,
        brightpath_csv_bytes,
        brightpath_company,
        csv_update,
        mock_llm_summary_response,
    ):
        """If LLM confidence < 0.5, status should be needs_review."""
        normaliser = NormaliserService()
        low_confidence_response = {
            "period": "Jan 2026",
            "metrics": {"revenue": 875000.0},
            "unmapped_data": [],
            "confidence": 0.3,
            "notes": "Very uncertain about the data layout.",
        }

        with (
            patch("app.services.normaliser.storage_service") as mock_storage,
            patch("app.services.normaliser.firestore_service") as mock_firestore,
            patch("app.services.normaliser.llm_service") as mock_llm,
        ):
            mock_storage.download_file = AsyncMock(return_value=brightpath_csv_bytes)
            mock_firestore.save_update = AsyncMock()
            mock_firestore.get_company = AsyncMock(return_value=brightpath_company)
            mock_firestore.get_previous_update = AsyncMock(return_value=None)
            mock_firestore.update_company = AsyncMock()
            mock_llm.call_json = AsyncMock(
                side_effect=[low_confidence_response, mock_llm_summary_response]
            )

            result = await normaliser.process_update(csv_update)

        assert result.processing_status == ProcessingStatus.NEEDS_REVIEW
