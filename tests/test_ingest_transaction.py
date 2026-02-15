"""Tests for ingest transaction safety and Pub/Sub integration."""

import base64
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.update import (
    ProcessingStatus,
    SourceFileType,
    SourceType,
    Update,
)


@pytest.fixture
def client():
    """Create a test client with mocked services."""
    from app.main import app

    return TestClient(app)


@pytest.fixture
def api_headers():
    return {"X-API-Key": "test-key"}


def _make_update(update_id: str = "upd-123") -> Update:
    """Create a proper Update model for response validation."""
    return Update(
        id=update_id,
        fund_id="f1",
        company_id="c1",
        source_type=SourceType.MANUAL_UPLOAD,
        source_file_type=SourceFileType.EXCEL,
        raw_file_urls=["gs://pe-copilot-raw-uploads/f1/c1/20260215_report.xlsx"],
        processing_status=ProcessingStatus.PENDING,
    )


class TestIngestTransactionSafety:
    """Verify that GCS + Firestore operations are transactional."""

    @patch("app.routers.ingest.pubsub_service")
    @patch("app.routers.ingest.firestore_service")
    @patch("app.routers.ingest.storage_service")
    def test_gcs_upload_failure_no_firestore_record(
        self, mock_storage, mock_firestore, mock_pubsub, client, api_headers
    ):
        """If GCS upload fails, no Firestore record should be created."""
        mock_storage.upload_raw_file = AsyncMock(side_effect=Exception("GCS unavailable"))

        response = client.post(
            "/api/v1/ingest/upload",
            headers=api_headers,
            data={"company_id": "c1", "fund_id": "f1", "period": "Jan 2026"},
            files={"file": ("report.xlsx", b"content", "application/octet-stream")},
        )

        assert response.status_code == 500
        mock_firestore.create_update.assert_not_called()
        mock_pubsub.publish_file_ingestion_event.assert_not_called()

    @patch("app.routers.ingest.pubsub_service")
    @patch("app.routers.ingest.firestore_service")
    @patch("app.routers.ingest.storage_service")
    def test_firestore_failure_cleans_up_gcs(
        self, mock_storage, mock_firestore, mock_pubsub, client, api_headers
    ):
        """If Firestore fails after GCS upload, GCS file should be deleted."""
        mock_storage.upload_raw_file = AsyncMock(
            return_value="gs://pe-copilot-raw-uploads/f1/c1/20260215_report.xlsx"
        )
        mock_storage.delete_file = AsyncMock()
        mock_firestore.create_update = AsyncMock(side_effect=Exception("Firestore write failed"))

        response = client.post(
            "/api/v1/ingest/upload",
            headers=api_headers,
            data={"company_id": "c1", "fund_id": "f1", "period": "Jan 2026"},
            files={"file": ("report.xlsx", b"content", "application/octet-stream")},
        )

        assert response.status_code == 500
        mock_storage.delete_file.assert_called_once_with(
            "gs://pe-copilot-raw-uploads/f1/c1/20260215_report.xlsx"
        )
        mock_pubsub.publish_file_ingestion_event.assert_not_called()

    @patch("app.routers.ingest.pubsub_service")
    @patch("app.routers.ingest.firestore_service")
    @patch("app.routers.ingest.storage_service")
    def test_pubsub_failure_upload_still_succeeds(
        self, mock_storage, mock_firestore, mock_pubsub, client, api_headers
    ):
        """If Pub/Sub fails, the upload should still succeed (update stays PENDING)."""
        mock_storage.upload_raw_file = AsyncMock(
            return_value="gs://pe-copilot-raw-uploads/f1/c1/20260215_report.xlsx"
        )
        mock_firestore.create_update = AsyncMock(return_value=_make_update("upd-123"))
        mock_pubsub.publish_file_ingestion_event = AsyncMock(
            side_effect=Exception("Pub/Sub topic not found")
        )

        response = client.post(
            "/api/v1/ingest/upload",
            headers=api_headers,
            data={"company_id": "c1", "fund_id": "f1", "period": "Jan 2026"},
            files={"file": ("report.xlsx", b"content", "application/octet-stream")},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == "upd-123"
        assert data["processing_status"] == "pending"
        mock_pubsub.publish_file_ingestion_event.assert_called_once()
        mock_storage.delete_file.assert_not_called()

    @patch("app.routers.ingest.pubsub_service")
    @patch("app.routers.ingest.firestore_service")
    @patch("app.routers.ingest.storage_service")
    def test_full_success_all_three_steps(
        self, mock_storage, mock_firestore, mock_pubsub, client, api_headers
    ):
        """Happy path: GCS upload + Firestore + Pub/Sub all succeed."""
        mock_storage.upload_raw_file = AsyncMock(
            return_value="gs://pe-copilot-raw-uploads/f1/c1/20260215_report.xlsx"
        )
        mock_firestore.create_update = AsyncMock(return_value=_make_update("upd-456"))
        mock_pubsub.publish_file_ingestion_event = AsyncMock(return_value="msg-789")

        response = client.post(
            "/api/v1/ingest/upload",
            headers=api_headers,
            data={"company_id": "c1", "fund_id": "f1", "period": "Jan 2026"},
            files={"file": ("report.xlsx", b"content", "application/octet-stream")},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == "upd-456"
        mock_storage.upload_raw_file.assert_called_once()
        mock_firestore.create_update.assert_called_once()
        mock_pubsub.publish_file_ingestion_event.assert_called_once_with(
            update_id="upd-456",
            fund_id="f1",
            company_id="c1",
        )


class TestProcessEventEndpoint:
    """Verify the Pub/Sub push callback endpoint."""

    def _make_pubsub_body(self, data: dict) -> dict:
        """Create a Pub/Sub push message body."""
        encoded = base64.b64encode(json.dumps(data).encode()).decode()
        return {
            "message": {
                "data": encoded,
                "messageId": "test-msg-1",
                "publishTime": "2026-02-15T10:00:00Z",
            },
            "subscription": "projects/test/subscriptions/test-sub",
        }

    @patch("app.routers.tasks.normaliser_service")
    @patch("app.routers.tasks.firestore_service")
    def test_process_event_success(self, mock_firestore, mock_normaliser, client):
        """Valid Pub/Sub message triggers processing."""
        mock_update = _make_update("upd-123")
        mock_firestore.get_update = AsyncMock(return_value=mock_update)

        processed = _make_update("upd-123")
        processed.processing_status = ProcessingStatus.COMPLETED
        mock_normaliser.process_update = AsyncMock(return_value=processed)

        body = self._make_pubsub_body({"update_id": "upd-123", "fund_id": "f1", "company_id": "c1"})
        response = client.post("/api/v1/internal/process-event", json=body)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["update_id"] == "upd-123"
        mock_normaliser.process_update.assert_called_once()

    @patch("app.routers.tasks.firestore_service")
    def test_process_event_skips_completed(self, mock_firestore, client):
        """Already-completed updates should be skipped."""
        mock_update = _make_update("upd-done")
        mock_update.processing_status = ProcessingStatus.COMPLETED
        mock_firestore.get_update = AsyncMock(return_value=mock_update)

        body = self._make_pubsub_body({"update_id": "upd-done"})
        response = client.post("/api/v1/internal/process-event", json=body)

        assert response.status_code == 200
        assert response.json()["status"] == "skipped"

    def test_process_event_no_data(self, client):
        """Message with no data should return error (but 200 to avoid retries)."""
        body = {"message": {}, "subscription": "test"}
        response = client.post("/api/v1/internal/process-event", json=body)

        assert response.status_code == 200
        assert response.json()["status"] == "error"

    def test_process_event_no_update_id(self, client):
        """Message without update_id should return error."""
        body = self._make_pubsub_body({"fund_id": "f1"})
        response = client.post("/api/v1/internal/process-event", json=body)

        assert response.status_code == 200
        assert response.json()["status"] == "error"
        assert "Missing update_id" in response.json()["detail"]

    @patch("app.routers.tasks.firestore_service")
    def test_process_event_update_not_found(self, mock_firestore, client):
        """Non-existent update_id should return error."""
        mock_firestore.get_update = AsyncMock(return_value=None)

        body = self._make_pubsub_body({"update_id": "nonexistent"})
        response = client.post("/api/v1/internal/process-event", json=body)

        assert response.status_code == 200
        assert response.json()["status"] == "error"
