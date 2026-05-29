"""Tests for the files download router."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


@pytest.fixture
def api_headers():
    return {"X-API-Key": "test-key"}


class TestFileDownload:
    """Tests for GET /api/v1/files/download."""

    @patch("app.routers.files.storage_service")
    def test_generates_signed_url(self, mock_storage, client, api_headers):
        """Valid GCS URL returns a signed download URL."""
        mock_storage.generate_signed_url = AsyncMock(
            return_value="https://storage.googleapis.com/signed-url"
        )

        resp = client.get(
            "/api/v1/files/download",
            params={"gcs_url": "gs://pe-copilot-raw-uploads/test.xlsx"},
            headers=api_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "download_url" in data
        assert data["download_url"] == "https://storage.googleapis.com/signed-url"
        assert data["expires_in"] == "1 hour"

    def test_rejects_invalid_gcs_url(self, client, api_headers):
        """Non-GCS URLs return 400."""
        resp = client.get(
            "/api/v1/files/download",
            params={"gcs_url": "https://example.com/file.xlsx"},
            headers=api_headers,
        )
        assert resp.status_code == 400

    def test_requires_api_key(self, client):
        """Missing API key returns 422 (header required)."""
        resp = client.get(
            "/api/v1/files/download",
            params={"gcs_url": "gs://bucket/file.xlsx"},
        )
        assert resp.status_code == 422

    def test_wrong_api_key_returns_401(self, client):
        """Wrong API key returns 401."""
        resp = client.get(
            "/api/v1/files/download",
            params={"gcs_url": "gs://bucket/file.xlsx"},
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 401

    @patch("app.routers.files.storage_service")
    def test_handles_storage_error(self, mock_storage, client, api_headers):
        """Storage service failure returns 500."""
        mock_storage.generate_signed_url = AsyncMock(
            side_effect=Exception("GCS unavailable")
        )

        resp = client.get(
            "/api/v1/files/download",
            params={"gcs_url": "gs://bucket/file.xlsx"},
            headers=api_headers,
        )
        assert resp.status_code == 500
