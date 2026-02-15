"""Pub/Sub service — publish events for asynchronous processing.

Events are published after file upload to trigger automatic processing
via a Pub/Sub push subscription to Cloud Run.
"""

import json
import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


class PubSubError(Exception):
    """Raised when a Pub/Sub operation fails."""


class PubSubService:
    """Handles Pub/Sub publishing operations."""

    def __init__(self) -> None:
        self._publisher: Any | None = None

    @property
    def publisher(self) -> Any:
        """Lazy-init the Pub/Sub publisher client."""
        if self._publisher is None:
            from google.cloud import pubsub_v1

            self._publisher = pubsub_v1.PublisherClient()
        return self._publisher

    def _topic_path(self, topic_name: str) -> str:
        """Build the full topic path: projects/{project}/topics/{topic}."""
        project_id = settings.gcp_project_id
        if not project_id:
            raise PubSubError("GCP_PROJECT_ID is not set — cannot publish to Pub/Sub")
        return self.publisher.topic_path(project_id, topic_name)

    async def publish_file_ingestion_event(
        self,
        update_id: str,
        fund_id: str,
        company_id: str,
    ) -> str:
        """Publish a file ingestion event to trigger processing.

        The Pub/Sub push subscription will call the /api/v1/internal/process-event
        endpoint on Cloud Run, which picks up the update_id and processes it.

        Returns the Pub/Sub message ID.
        Raises PubSubError on failure.
        """
        topic_path = self._topic_path(settings.pubsub_file_ingestion_topic)

        message_data = {
            "update_id": update_id,
            "fund_id": fund_id,
            "company_id": company_id,
            "event_type": "file_ingestion",
        }

        message_bytes = json.dumps(message_data).encode("utf-8")

        try:
            # publish() is synchronous and returns a Future
            future = self.publisher.publish(topic_path, message_bytes)
            message_id = future.result(timeout=30)

            logger.info(
                "Published file ingestion event for update %s (message_id: %s)",
                update_id, message_id,
            )
            return message_id

        except Exception as exc:
            logger.error(
                "Failed to publish file ingestion event for update %s: %s",
                update_id, exc,
            )
            raise PubSubError(
                f"Failed to publish event for update {update_id}: {exc}"
            ) from exc


# Singleton
pubsub_service = PubSubService()
