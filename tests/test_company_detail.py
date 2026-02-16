"""Tests for company detail endpoint and metrics history."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.company import Company
from app.models.dashboard import CompanyDetailView, UpdateSummaryDetail
from app.models.task import Task, TaskPriority, TaskStatus
from app.models.update import ProcessingStatus, SourceFileType, Update
from app.services.firestore import FirestoreService


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


@pytest.fixture
def api_headers():
    return {"X-API-Key": "test-key"}


def _make_company(company_id: str = "c1") -> Company:
    return Company(
        id=company_id,
        fund_id="f1",
        name="TestCorp",
        sector="Technology",
        health_status="green",
        health_reasons=[],
        accounting_system="Xero",
        reporting_frequency="monthly",
        primary_contact_name="Jane Smith",
        primary_contact_email="jane@testcorp.com",
        created_at=datetime(2025, 1, 1),
    )


def _make_update(update_id: str, period: str, **kwargs) -> Update:
    defaults = dict(
        id=update_id,
        fund_id="f1",
        company_id="c1",
        received_at=datetime(2026, 1, 15),
        source_type="manual_upload",
        source_file_type=SourceFileType.EXCEL,
        processing_status=ProcessingStatus.COMPLETED,
        llm_confidence=0.92,
        llm_summary=f"Performance summary for {period}",
        llm_risks=["Supply chain risk"],
        llm_action_items=["Review contracts"],
        normalised_metrics={"revenue": 1_000_000, "ebitda": 250_000},
        variances={"revenue": 0.05, "ebitda": -0.02},
        missing_metrics=[],
        metrics_period=period,
    )
    defaults.update(kwargs)
    return Update(**defaults)


def _make_task(task_id: str = "t1") -> Task:
    return Task(
        id=task_id,
        fund_id="f1",
        company_id="c1",
        description="Review Q4 variance",
        priority=TaskPriority.HIGH,
        status=TaskStatus.PENDING,
        created_at=datetime(2026, 1, 10),
    )


def _make_detail_view() -> CompanyDetailView:
    company = _make_company()
    update = _make_update("u1", "Jan 2026")
    task = _make_task()

    return CompanyDetailView(
        company=company,
        updates=[
            UpdateSummaryDetail(
                id=update.id,
                received_at=update.received_at,
                source_file_type=update.source_file_type,
                metrics_period=update.metrics_period,
                processing_status=update.processing_status,
                llm_confidence=update.llm_confidence,
                llm_summary=update.llm_summary,
                llm_risks=update.llm_risks,
                llm_action_items=update.llm_action_items,
                normalised_metrics=update.normalised_metrics,
                variances=update.variances,
                missing_metrics=update.missing_metrics,
            )
        ],
        pending_tasks=[task],
        metrics_history={
            "revenue": [{"period": "Jan 2026", "value": 1_000_000, "variance": 0.05}],
        },
    )


class TestCompanyDetailEndpoint:
    """Tests for GET /api/v1/companies/{company_id}/detail."""

    @patch("app.routers.companies.firestore_service")
    def test_returns_200_with_detail(self, mock_service, client, api_headers):
        """Happy path — returns full company detail view."""
        mock_service.get_company_detail_view = AsyncMock(return_value=_make_detail_view())

        res = client.get("/api/v1/companies/c1/detail?fund_id=f1", headers=api_headers)

        assert res.status_code == 200
        data = res.json()
        assert data["company"]["name"] == "TestCorp"
        assert data["company"]["sector"] == "Technology"
        assert len(data["updates"]) == 1
        assert data["updates"][0]["metrics_period"] == "Jan 2026"
        assert len(data["pending_tasks"]) == 1
        assert data["pending_tasks"][0]["description"] == "Review Q4 variance"
        assert "revenue" in data["metrics_history"]

    @patch("app.routers.companies.firestore_service")
    def test_returns_404_when_company_not_found(self, mock_service, client, api_headers):
        """Returns 404 when company doesn't exist."""
        mock_service.get_company_detail_view = AsyncMock(
            side_effect=ValueError("Company xyz not found")
        )

        res = client.get("/api/v1/companies/xyz/detail?fund_id=f1", headers=api_headers)

        assert res.status_code == 404
        assert "not found" in res.json()["detail"]

    def test_requires_fund_id(self, client, api_headers):
        """Returns 422 when fund_id query param is missing."""
        res = client.get("/api/v1/companies/c1/detail", headers=api_headers)

        assert res.status_code == 422

    @patch("app.routers.companies.firestore_service")
    def test_update_summary_excludes_extracted_text(self, mock_service, client, api_headers):
        """UpdateSummaryDetail should not contain extracted_text."""
        mock_service.get_company_detail_view = AsyncMock(return_value=_make_detail_view())

        res = client.get("/api/v1/companies/c1/detail?fund_id=f1", headers=api_headers)

        data = res.json()
        for update in data["updates"]:
            assert "extracted_text" not in update


class TestMetricsHistory:
    """Tests for _build_metrics_history helper."""

    def test_builds_oldest_first(self):
        """Metrics history should be ordered oldest first (for charting).

        Note: updates are passed newest-first (matching list_updates DESC),
        and _build_metrics_history reverses them internally.
        """
        updates = [
            _make_update("u3", "Feb 2026",
                         normalised_metrics={"revenue": 1_050_000},
                         variances={"revenue": 0.05},
                         received_at=datetime(2026, 2, 15)),
            _make_update("u2", "Jan 2026",
                         normalised_metrics={"revenue": 1_000_000},
                         variances={"revenue": 0.11},
                         received_at=datetime(2026, 1, 15)),
            _make_update("u1", "Dec 2025",
                         normalised_metrics={"revenue": 900_000},
                         variances={},
                         received_at=datetime(2025, 12, 15)),
        ]

        service = FirestoreService()
        history = service._build_metrics_history(updates)

        assert "revenue" in history
        assert len(history["revenue"]) == 3
        # Oldest first (updates are passed newest-first, reversed internally)
        assert history["revenue"][0]["period"] == "Dec 2025"
        assert history["revenue"][0]["value"] == 900_000
        assert history["revenue"][1]["period"] == "Jan 2026"
        assert history["revenue"][2]["period"] == "Feb 2026"
        assert history["revenue"][2]["variance"] == 0.05

    def test_empty_updates_returns_empty_dict(self):
        """Empty update list returns empty metrics history."""
        service = FirestoreService()
        history = service._build_metrics_history([])
        assert history == {}

    def test_multiple_metrics_tracked(self):
        """Each metric gets its own history list."""
        updates = [
            _make_update("u1", "Jan 2026",
                         normalised_metrics={"revenue": 1_000_000, "ebitda": 250_000, "headcount": 45},
                         variances={"revenue": 0.05}),
        ]

        service = FirestoreService()
        history = service._build_metrics_history(updates)

        assert len(history) == 3
        assert "revenue" in history
        assert "ebitda" in history
        assert "headcount" in history
        assert history["headcount"][0]["value"] == 45
