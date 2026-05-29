"""Tests for model tiering — Sonnet for normalisation, Haiku for summarisation."""

from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services.normaliser import NormaliserService


class TestModelRouting:
    """Verify the correct model is used for each LLM call."""

    @patch("app.services.normaliser.llm_service")
    async def test_normalisation_uses_sonnet(self, mock_llm):
        """Layer 2 normalisation should use the Sonnet model."""
        mock_llm.call_json = AsyncMock(return_value={
            "period": "Jan 2026",
            "metrics": {"revenue": 1_000_000},
            "unmapped_data": [],
            "confidence": 0.9,
            "notes": "",
        })

        service = NormaliserService()
        await service._normalise(
            extracted_text="Revenue | 1,000,000",
            company_name="TestCorp",
            sector="Technology",
            accounting_system="Xero",
            mapping_instructions="Revenue is labelled Revenue",
            metric_schema=[{"name": "revenue", "label": "Revenue", "type": "currency"}],
        )

        call_kwargs = mock_llm.call_json.call_args[1]
        assert call_kwargs["model"] == settings.claude_model_normalisation
        assert "sonnet" in call_kwargs["model"].lower()

    @patch("app.services.normaliser.llm_service")
    async def test_summarisation_uses_haiku(self, mock_llm):
        """Summarisation should use the fast (Haiku) model."""
        mock_llm.call_json = AsyncMock(return_value={
            "summary": "Revenue grew 5% to £1M.",
            "risks": [],
            "action_items": [],
        })

        service = NormaliserService()
        await service._summarise(
            company_name="TestCorp",
            sector="Technology",
            period="Jan 2026",
            normalised_metrics={"revenue": 1_000_000},
            previous_metrics={"revenue": 950_000},
            variances={"revenue": 0.05},
            raw_context="some extracted text",
        )

        call_kwargs = mock_llm.call_json.call_args[1]
        assert call_kwargs["model"] == settings.claude_model_fast
        assert "haiku" in call_kwargs["model"].lower()

    @patch("app.services.normaliser.llm_service")
    async def test_summarisation_max_tokens_reduced(self, mock_llm):
        """Summarisation should use a reduced max_tokens (2048 not 4096)."""
        mock_llm.call_json = AsyncMock(return_value={
            "summary": "Revenue grew.", "risks": [], "action_items": [],
        })

        service = NormaliserService()
        await service._summarise(
            company_name="TestCorp",
            sector="Tech",
            period="Jan 2026",
            normalised_metrics={"revenue": 1_000_000},
            previous_metrics={},
            variances={},
            raw_context="text",
        )

        call_kwargs = mock_llm.call_json.call_args[1]
        assert call_kwargs["max_tokens"] == 2048
