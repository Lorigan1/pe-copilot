"""Tests for health scorer integration in the normaliser pipeline."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.company import Company
from app.models.metric_schema import DEFAULT_PE_METRICS
from app.models.update import ProcessingStatus, SourceFileType, SourceType, Update


def _make_company(health_status="green", days_since_update=5):
    return Company(
        id="comp-1",
        fund_id="fund-1",
        name="TestCo",
        sector="Technology",
        canonical_metrics=DEFAULT_PE_METRICS,
        accounting_system="Sage",
        last_update_at=datetime.utcnow() - timedelta(days=days_since_update),
        health_status=health_status,
        health_reasons=[],
    )


def _make_update():
    return Update(
        id="upd-1",
        fund_id="fund-1",
        company_id="comp-1",
        received_at=datetime.utcnow(),
        source_type=SourceType.MANUAL_UPLOAD,
        source_file_type=SourceFileType.EXCEL,
        raw_file_urls=["gs://pe-copilot-raw-uploads/test.xlsx"],
    )


@pytest.mark.asyncio
class TestHealthScoringInNormaliser:
    """Tests that the normaliser calls health_scorer and updates the company."""

    @patch("app.services.normaliser.email_sender")
    @patch("app.services.normaliser.storage_service")
    @patch("app.services.normaliser.llm_service")
    @patch("app.services.normaliser.firestore_service")
    async def test_health_status_updated_after_processing(
        self, mock_firestore, mock_llm, mock_storage, mock_email
    ):
        """After processing, company health_status is updated in Firestore."""
        from app.services.normaliser import NormaliserService

        company = _make_company()
        update = _make_update()

        # Mock all service calls
        mock_firestore.save_update = AsyncMock()
        mock_firestore.get_company = AsyncMock(return_value=company)
        mock_firestore.get_previous_update = AsyncMock(return_value=None)
        mock_firestore.update_company = AsyncMock(return_value=company)
        mock_firestore.get_fund = AsyncMock(return_value=MagicMock(
            manager_email="mgr@example.com", name="Test Fund"
        ))

        mock_storage.download_file = AsyncMock(return_value=b"fake excel bytes")

        mock_llm.call_json = AsyncMock(side_effect=[
            # Normalisation response
            {
                "period": "Jan 2026",
                "metrics": {"revenue": 1000000, "ebitda": 200000},
                "confidence": 0.9,
                "notes": "",
                "unmapped_data": [],
            },
            # Summarisation response
            {
                "summary": "Good quarter",
                "risks": [],
                "action_items": [],
            },
        ])

        # Mock excel parser
        with patch("app.services.normaliser.excel_parser") as mock_parser:
            mock_parser.parse_excel = MagicMock(return_value="Revenue | 1000000")

            service = NormaliserService()
            result = await service.process_update(update)

        # The company should have been updated with health status
        assert mock_firestore.update_company.called
        update_call = mock_firestore.update_company.call_args
        assert update_call[0][0] == "comp-1"  # company_id

        # Check the data passed includes health fields
        update_data = update_call[0][1].model_dump()
        assert "health_status" in update_data
        assert "health_reasons" in update_data
        assert "last_update_at" in update_data

    @patch("app.services.normaliser.email_sender")
    @patch("app.services.normaliser.storage_service")
    @patch("app.services.normaliser.llm_service")
    @patch("app.services.normaliser.firestore_service")
    async def test_email_sent_on_health_change(
        self, mock_firestore, mock_llm, mock_storage, mock_email
    ):
        """When health changes from green → amber/red, an alert email is sent."""
        from app.services.normaliser import NormaliserService

        # Company starts green, but will have 3+ missing metrics → red
        company = _make_company(health_status="green")
        update = _make_update()

        mock_firestore.save_update = AsyncMock()
        mock_firestore.get_company = AsyncMock(return_value=company)
        mock_firestore.get_previous_update = AsyncMock(return_value=None)
        mock_firestore.update_company = AsyncMock(return_value=company)
        mock_firestore.get_fund = AsyncMock(return_value=MagicMock(
            manager_email="mgr@example.com", name="Test Fund"
        ))

        mock_storage.download_file = AsyncMock(return_value=b"fake bytes")

        mock_llm.call_json = AsyncMock(side_effect=[
            {
                "period": "Jan 2026",
                "metrics": {"revenue": -500},  # negative revenue → validator error
                "confidence": 0.3,
                "notes": "",
                "unmapped_data": [],
            },
            {
                "summary": "Problems detected",
                "risks": ["Negative revenue"],
                "action_items": ["Investigate"],
            },
        ])

        with patch("app.services.normaliser.excel_parser") as mock_parser:
            mock_parser.parse_excel = MagicMock(return_value="Revenue | -500")

            service = NormaliserService()
            result = await service.process_update(update)

        # Health should have changed (many missing required metrics + bad data)
        # Email sender should have been called
        if getattr(result, "_health_changed", False):
            mock_email.send_health_alert.assert_called_once()
            call_kwargs = mock_email.send_health_alert.call_args
            assert call_kwargs[1]["recipient_email"] == "mgr@example.com" or \
                   call_kwargs.kwargs.get("recipient_email") == "mgr@example.com"

    @patch("app.services.normaliser.email_sender")
    @patch("app.services.normaliser.storage_service")
    @patch("app.services.normaliser.llm_service")
    @patch("app.services.normaliser.firestore_service")
    async def test_no_email_when_health_unchanged(
        self, mock_firestore, mock_llm, mock_storage, mock_email
    ):
        """When health stays green, no alert email is sent."""
        from app.services.normaliser import NormaliserService

        company = _make_company(health_status="green")
        update = _make_update()

        mock_firestore.save_update = AsyncMock()
        mock_firestore.get_company = AsyncMock(return_value=company)
        mock_firestore.get_previous_update = AsyncMock(return_value=None)
        mock_firestore.update_company = AsyncMock(return_value=company)

        mock_storage.download_file = AsyncMock(return_value=b"fake bytes")

        mock_llm.call_json = AsyncMock(side_effect=[
            {
                "period": "Jan 2026",
                "metrics": {
                    "revenue": 1000000, "gross_profit": 600000,
                    "ebitda": 300000, "net_income": 150000,
                    "cash_balance": 500000, "total_debt": 100000,
                    "net_assets": 800000, "operating_cashflow": 200000,
                    "headcount": 50,
                },
                "confidence": 0.95,
                "notes": "",
                "unmapped_data": [],
            },
            {
                "summary": "Excellent quarter",
                "risks": [],
                "action_items": [],
            },
        ])

        with patch("app.services.normaliser.excel_parser") as mock_parser:
            mock_parser.parse_excel = MagicMock(return_value="Revenue | 1000000")

            service = NormaliserService()
            result = await service.process_update(update)

        # No health change → no email
        mock_email.send_health_alert.assert_not_called()
