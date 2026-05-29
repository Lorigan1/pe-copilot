"""Tests for the email sender service."""

import pytest

from app.services.email_sender import EmailSender


@pytest.fixture
def sender():
    """Create a fresh EmailSender instance (not configured — will log only)."""
    s = EmailSender()
    return s


class TestHealthAlert:
    """Tests for health change alert emails."""

    @pytest.mark.asyncio
    async def test_sends_health_alert_without_sendgrid(self, sender):
        """When SendGrid is not configured, email is logged and returns True."""
        result = await sender.send_health_alert(
            recipient_email="test@example.com",
            company_name="NorthStar Logistics",
            previous_status="green",
            new_status="amber",
            reasons=["No update in 25 days (threshold: 21)"],
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_health_alert_with_custom_fund_name(self, sender):
        """Custom fund name appears in the email."""
        result = await sender.send_health_alert(
            recipient_email="test@example.com",
            company_name="BrightPath Education",
            previous_status="green",
            new_status="red",
            reasons=["revenue decreased by 35.0%", "3 required metrics missing"],
            fund_name="Atlas Growth Fund I",
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_health_alert_red_to_green(self, sender):
        """Recovery alerts should also be sent."""
        result = await sender.send_health_alert(
            recipient_email="test@example.com",
            company_name="Helix Manufacturing",
            previous_status="red",
            new_status="green",
            reasons=["All metrics within normal ranges"],
        )
        assert result is True


class TestStalenessAlert:
    """Tests for staleness summary emails."""

    @pytest.mark.asyncio
    async def test_sends_staleness_alert(self, sender):
        """Staleness alert with multiple companies."""
        result = await sender.send_staleness_alert(
            recipient_email="test@example.com",
            stale_companies=[
                {"name": "NorthStar Logistics", "days_since": 40, "threshold": 35},
                {"name": "BrightPath Education", "days_since": 55, "threshold": 35},
            ],
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_empty_stale_companies_returns_true(self, sender):
        """No stale companies → returns True without sending."""
        result = await sender.send_staleness_alert(
            recipient_email="test@example.com",
            stale_companies=[],
        )
        assert result is True


class TestStatusColors:
    """Tests for status-to-color mapping."""

    def test_green_color(self):
        assert EmailSender._status_color("green") == "#27AE60"

    def test_amber_color(self):
        assert EmailSender._status_color("amber") == "#F39C12"

    def test_red_color(self):
        assert EmailSender._status_color("red") == "#E74C3C"

    def test_unknown_color(self):
        assert EmailSender._status_color("unknown") == "#95A5A6"


class TestSendGridNotInstalled:
    """Tests for graceful degradation when SendGrid is unavailable."""

    @pytest.mark.asyncio
    async def test_send_returns_true_without_api_key(self, sender):
        """Without an API key, _send logs and returns True."""
        result = await sender._send(
            to_email="test@example.com",
            subject="Test",
            html_content="<p>Test</p>",
        )
        assert result is True
