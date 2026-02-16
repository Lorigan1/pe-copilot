"""Tests for content-based file deduplication on upload."""

import hashlib
import io
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.update import ProcessingStatus, SourceFileType, SourceType, Update


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


@pytest.fixture
def api_headers():
    return {"X-API-Key": "test-key"}


def _make_update(update_id: str = "u1", **kwargs) -> Update:
    defaults = dict(
        id=update_id,
        fund_id="f1",
        company_id="c1",
        received_at=datetime(2026, 1, 15),
        source_type=SourceType.MANUAL_UPLOAD,
        source_file_type=SourceFileType.CSV,
        raw_file_urls=["gs://bucket/f1/c1/file.csv"],
        metrics_period="Jan 2026",
        processing_status=ProcessingStatus.COMPLETED,
        file_content_hash="abc123",
    )
    defaults.update(kwargs)
    return Update(**defaults)


class TestDuplicateDetection:
    """Tests for the dedup check in the upload endpoint."""

    @patch("app.routers.ingest.pubsub_service")
    @patch("app.routers.ingest.storage_service")
    @patch("app.routers.ingest.firestore_service")
    def test_duplicate_file_returns_409(
        self, mock_firestore, mock_storage, mock_pubsub, client, api_headers
    ):
        """Uploading the same file content twice returns 409 Conflict."""
        file_content = b"revenue,100000\nebitda,50000"
        expected_hash = hashlib.sha256(file_content).hexdigest()

        existing = _make_update(file_content_hash=expected_hash)
        mock_firestore.find_duplicate_update = AsyncMock(return_value=existing)

        res = client.post(
            "/api/v1/ingest/upload",
            headers=api_headers,
            data={"company_id": "c1", "fund_id": "f1", "period": "Jan 2026"},
            files={"file": ("report.csv", io.BytesIO(file_content), "text/csv")},
        )

        assert res.status_code == 409
        assert "Duplicate file detected" in res.json()["detail"]
        assert "u1" in res.json()["detail"]
        # Should NOT have uploaded to GCS or created a Firestore record
        mock_storage.upload_raw_file.assert_not_called()
        mock_firestore.create_update.assert_not_called()

    @patch("app.routers.ingest.pubsub_service")
    @patch("app.routers.ingest.storage_service")
    @patch("app.routers.ingest.firestore_service")
    def test_different_content_same_name_creates_new(
        self, mock_firestore, mock_storage, mock_pubsub, client, api_headers
    ):
        """Different content with the same filename should create a new update."""
        mock_firestore.find_duplicate_update = AsyncMock(return_value=None)
        mock_storage.upload_raw_file = AsyncMock(return_value="gs://bucket/path.csv")
        new_update = _make_update("u2", file_content_hash="new_hash")
        mock_firestore.create_update = AsyncMock(return_value=new_update)
        mock_pubsub.publish_file_ingestion_event = AsyncMock()

        res = client.post(
            "/api/v1/ingest/upload",
            headers=api_headers,
            data={"company_id": "c1", "fund_id": "f1", "period": "Jan 2026"},
            files={"file": ("report.csv", io.BytesIO(b"different content"), "text/csv")},
        )

        assert res.status_code == 201

    @patch("app.routers.ingest.pubsub_service")
    @patch("app.routers.ingest.storage_service")
    @patch("app.routers.ingest.firestore_service")
    def test_same_content_different_name_detected(
        self, mock_firestore, mock_storage, mock_pubsub, client, api_headers
    ):
        """Same content under a different filename should still be caught."""
        file_content = b"identical content"
        expected_hash = hashlib.sha256(file_content).hexdigest()

        existing = _make_update(file_content_hash=expected_hash)
        mock_firestore.find_duplicate_update = AsyncMock(return_value=existing)

        res = client.post(
            "/api/v1/ingest/upload",
            headers=api_headers,
            data={"company_id": "c1", "fund_id": "f1"},
            files={"file": ("totally_different_name.csv", io.BytesIO(file_content), "text/csv")},
        )

        assert res.status_code == 409

    @patch("app.routers.ingest.pubsub_service")
    @patch("app.routers.ingest.storage_service")
    @patch("app.routers.ingest.firestore_service")
    def test_file_hash_stored_on_update(
        self, mock_firestore, mock_storage, mock_pubsub, client, api_headers
    ):
        """The file_content_hash should be passed through to the UpdateCreate."""
        file_content = b"test content for hashing"
        expected_hash = hashlib.sha256(file_content).hexdigest()

        mock_firestore.find_duplicate_update = AsyncMock(return_value=None)
        mock_storage.upload_raw_file = AsyncMock(return_value="gs://bucket/path.csv")
        mock_firestore.create_update = AsyncMock(
            return_value=_make_update(file_content_hash=expected_hash)
        )
        mock_pubsub.publish_file_ingestion_event = AsyncMock()

        client.post(
            "/api/v1/ingest/upload",
            headers=api_headers,
            data={"company_id": "c1", "fund_id": "f1"},
            files={"file": ("data.csv", io.BytesIO(file_content), "text/csv")},
        )

        # Check the UpdateCreate passed to create_update has the hash
        call_args = mock_firestore.create_update.call_args
        update_data = call_args[0][0]  # First positional arg
        assert update_data.file_content_hash == expected_hash

    @patch("app.routers.ingest.pubsub_service")
    @patch("app.routers.ingest.storage_service")
    @patch("app.routers.ingest.firestore_service")
    def test_hash_query_scoped_to_company(
        self, mock_firestore, mock_storage, mock_pubsub, client, api_headers
    ):
        """Dedup check should scope the query to the specific company_id."""
        file_content = b"some data"

        mock_firestore.find_duplicate_update = AsyncMock(return_value=None)
        mock_storage.upload_raw_file = AsyncMock(return_value="gs://bucket/path.csv")
        mock_firestore.create_update = AsyncMock(return_value=_make_update())
        mock_pubsub.publish_file_ingestion_event = AsyncMock()

        client.post(
            "/api/v1/ingest/upload",
            headers=api_headers,
            data={"company_id": "c99", "fund_id": "f1"},
            files={"file": ("data.csv", io.BytesIO(file_content), "text/csv")},
        )

        # Verify find_duplicate_update was called with the correct company_id
        mock_firestore.find_duplicate_update.assert_called_once()
        call_args = mock_firestore.find_duplicate_update.call_args
        assert call_args[0][0] == "c99"  # company_id


class TestFindDuplicateUpdate:
    """Unit tests for the FirestoreService.find_duplicate_update method."""

    def test_no_hash_returns_none(self):
        """Empty hash should short-circuit and return None."""
        from app.services.firestore import FirestoreService
        import asyncio

        service = FirestoreService()
        result = asyncio.get_event_loop().run_until_complete(
            service.find_duplicate_update("c1", "")
        )
        assert result is None
