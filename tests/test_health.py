"""Tests for the health check and basic app functionality."""


def test_health_check(client):
    """Health endpoint returns 200 with app info."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "PE CoPilot" in data["app"]


def test_root(client):
    """Root endpoint returns navigation links."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "docs" in data
    assert "upload" in data


def test_api_requires_auth(client):
    """API endpoints require X-API-Key header."""
    response = client.get("/api/v1/companies?fund_id=test")
    assert response.status_code == 422  # Missing required header


def test_api_rejects_bad_key(client):
    """API endpoints reject invalid API keys."""
    response = client.get(
        "/api/v1/companies?fund_id=test",
        headers={"X-API-Key": "wrong-key"},
    )
    assert response.status_code == 401
