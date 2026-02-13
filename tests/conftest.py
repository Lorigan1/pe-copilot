"""Shared test fixtures for PE CoPilot tests."""

import os

import pytest
from fastapi.testclient import TestClient

# Set test environment before importing app
os.environ["API_KEY"] = "test-key"
os.environ["GCP_PROJECT_ID"] = "test-project"
os.environ["ANTHROPIC_API_KEY"] = "test-key"
os.environ["DEBUG"] = "true"


@pytest.fixture
def client():
    """FastAPI test client."""
    from app.main import app

    return TestClient(app)


@pytest.fixture
def api_headers():
    """Standard headers for API requests."""
    return {"X-API-Key": "test-key"}
