"""Tests for the Pub/Sub publisher service."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.pubsub import PubSubError, PubSubService


class TestPubSubService:
    """Verify Pub/Sub service message publishing."""

    def setup_method(self):
        self.svc = PubSubService()

    def test_topic_path_requires_project_id(self):
        """Should raise PubSubError if GCP_PROJECT_ID is not set."""
        with patch("app.services.pubsub.settings") as mock_settings:
            mock_settings.gcp_project_id = ""
            with pytest.raises(PubSubError, match="GCP_PROJECT_ID is not set"):
                self.svc._topic_path("my-topic")

    @pytest.mark.asyncio
    async def test_publish_creates_correct_message(self):
        """Verify the message payload format published to Pub/Sub."""
        mock_publisher = MagicMock()
        mock_future = MagicMock()
        mock_future.result.return_value = "msg-123"
        mock_publisher.publish.return_value = mock_future
        mock_publisher.topic_path.return_value = "projects/test/topics/file-ingestion-events"

        self.svc._publisher = mock_publisher

        with patch("app.services.pubsub.settings") as mock_settings:
            mock_settings.gcp_project_id = "test-project"
            mock_settings.pubsub_file_ingestion_topic = "file-ingestion-events"

            message_id = await self.svc.publish_file_ingestion_event(
                update_id="upd-abc",
                fund_id="fund-123",
                company_id="comp-456",
            )

        assert message_id == "msg-123"

        # Verify the message body
        call_args = mock_publisher.publish.call_args
        topic_arg = call_args[0][0]
        data_arg = call_args[0][1]

        assert topic_arg == "projects/test/topics/file-ingestion-events"

        payload = json.loads(data_arg.decode("utf-8"))
        assert payload["update_id"] == "upd-abc"
        assert payload["fund_id"] == "fund-123"
        assert payload["company_id"] == "comp-456"
        assert payload["event_type"] == "file_ingestion"

    @pytest.mark.asyncio
    async def test_publish_returns_message_id(self):
        """Verify the returned message ID matches what Pub/Sub returns."""
        mock_publisher = MagicMock()
        mock_future = MagicMock()
        mock_future.result.return_value = "msg-xyz-789"
        mock_publisher.publish.return_value = mock_future
        mock_publisher.topic_path.return_value = "projects/p/topics/t"

        self.svc._publisher = mock_publisher

        with patch("app.services.pubsub.settings") as mock_settings:
            mock_settings.gcp_project_id = "p"
            mock_settings.pubsub_file_ingestion_topic = "t"

            result = await self.svc.publish_file_ingestion_event("u1", "f1", "c1")

        assert result == "msg-xyz-789"

    @pytest.mark.asyncio
    async def test_publish_failure_raises_pubsub_error(self):
        """Verify that publish failures are wrapped in PubSubError."""
        mock_publisher = MagicMock()
        mock_future = MagicMock()
        mock_future.result.side_effect = Exception("Network error")
        mock_publisher.publish.return_value = mock_future
        mock_publisher.topic_path.return_value = "projects/p/topics/t"

        self.svc._publisher = mock_publisher

        with patch("app.services.pubsub.settings") as mock_settings:
            mock_settings.gcp_project_id = "p"
            mock_settings.pubsub_file_ingestion_topic = "t"

            with pytest.raises(PubSubError, match="Failed to publish"):
                await self.svc.publish_file_ingestion_event("u1", "f1", "c1")

    @pytest.mark.asyncio
    async def test_publish_timeout_in_future_result(self):
        """Verify the publish call uses a 30s timeout on the future."""
        mock_publisher = MagicMock()
        mock_future = MagicMock()
        mock_future.result.return_value = "msg-1"
        mock_publisher.publish.return_value = mock_future
        mock_publisher.topic_path.return_value = "projects/p/topics/t"

        self.svc._publisher = mock_publisher

        with patch("app.services.pubsub.settings") as mock_settings:
            mock_settings.gcp_project_id = "p"
            mock_settings.pubsub_file_ingestion_topic = "t"

            await self.svc.publish_file_ingestion_event("u1", "f1", "c1")

        mock_future.result.assert_called_once_with(timeout=30)
