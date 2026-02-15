"""Tests for the staleness check endpoint."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.routers.tasks import _DEFAULT_STALENESS_DAYS, _STALENESS_THRESHOLDS


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


def _make_company(company_id: str, name: str, frequency: str = "monthly") -> MagicMock:
    """Create a mock Company object."""
    company = MagicMock()
    company.id = company_id
    company.name = name
    company.reporting_frequency = frequency
    return company


def _make_update(status: str = "completed", days_ago: int = 10) -> MagicMock:
    """Create a mock Update object."""
    update = MagicMock()
    update.processing_status = status
    update.received_at = datetime.utcnow() - timedelta(days=days_ago)
    return update


class TestStalenessThresholds:
    """Verify staleness threshold configuration."""

    def test_monthly_threshold(self):
        assert _STALENESS_THRESHOLDS["monthly"] == 35

    def test_quarterly_threshold(self):
        assert _STALENESS_THRESHOLDS["quarterly"] == 100

    def test_annually_threshold(self):
        assert _STALENESS_THRESHOLDS["annually"] == 380

    def test_varies_threshold(self):
        assert _STALENESS_THRESHOLDS["varies"] == 60

    def test_default_threshold(self):
        assert _DEFAULT_STALENESS_DAYS == 60


class TestStalenessCheck:
    """Verify the staleness check endpoint logic."""

    @patch("app.routers.tasks.firestore_service")
    def test_no_companies_returns_zero(self, mock_fs, client):
        """Fund with no companies should return 0 tasks."""
        mock_fs.list_companies = AsyncMock(return_value=[])

        response = client.post("/api/v1/internal/staleness-check?fund_id=f1")

        assert response.status_code == 200
        data = response.json()
        assert data["tasks_created"] == 0
        assert data["companies_checked"] == 0

    @patch("app.routers.tasks.firestore_service")
    def test_recent_update_not_stale(self, mock_fs, client):
        """Company with a recent completed update should NOT be stale."""
        company = _make_company("c1", "Fresh Co", "monthly")
        mock_fs.list_companies = AsyncMock(return_value=[company])

        # 10 days ago — well within the 35-day monthly threshold
        recent_update = _make_update(status="completed", days_ago=10)
        mock_fs.list_updates = AsyncMock(return_value=[recent_update])

        response = client.post("/api/v1/internal/staleness-check?fund_id=f1")

        assert response.status_code == 200
        data = response.json()
        assert data["tasks_created"] == 0
        assert data["companies_checked"] == 1
        mock_fs.create_task.assert_not_called()

    @patch("app.routers.tasks.firestore_service")
    def test_old_monthly_update_is_stale(self, mock_fs, client):
        """Company with update > 35 days old should be stale."""
        company = _make_company("c1", "Stale Monthly Co", "monthly")
        mock_fs.list_companies = AsyncMock(return_value=[company])

        # 40 days ago — exceeds the 35-day monthly threshold
        old_update = _make_update(status="completed", days_ago=40)
        mock_fs.list_updates = AsyncMock(return_value=[old_update])

        mock_task = MagicMock()
        mock_task.id = "task-1"
        mock_fs.create_task = AsyncMock(return_value=mock_task)

        response = client.post("/api/v1/internal/staleness-check?fund_id=f1")

        assert response.status_code == 200
        data = response.json()
        assert data["tasks_created"] == 1
        mock_fs.create_task.assert_called_once()

    @patch("app.routers.tasks.firestore_service")
    def test_old_quarterly_not_stale_within_threshold(self, mock_fs, client):
        """Quarterly company at 80 days should NOT be stale (threshold = 100)."""
        company = _make_company("c1", "Quarterly Co", "quarterly")
        mock_fs.list_companies = AsyncMock(return_value=[company])

        update = _make_update(status="completed", days_ago=80)
        mock_fs.list_updates = AsyncMock(return_value=[update])

        response = client.post("/api/v1/internal/staleness-check?fund_id=f1")

        assert response.status_code == 200
        assert response.json()["tasks_created"] == 0
        mock_fs.create_task.assert_not_called()

    @patch("app.routers.tasks.firestore_service")
    def test_old_quarterly_beyond_threshold_is_stale(self, mock_fs, client):
        """Quarterly company at 110 days should be stale (threshold = 100)."""
        company = _make_company("c1", "Old Quarterly Co", "quarterly")
        mock_fs.list_companies = AsyncMock(return_value=[company])

        update = _make_update(status="completed", days_ago=110)
        mock_fs.list_updates = AsyncMock(return_value=[update])

        mock_task = MagicMock()
        mock_task.id = "task-2"
        mock_fs.create_task = AsyncMock(return_value=mock_task)

        response = client.post("/api/v1/internal/staleness-check?fund_id=f1")

        assert response.status_code == 200
        assert response.json()["tasks_created"] == 1

    @patch("app.routers.tasks.firestore_service")
    def test_no_completed_updates_is_stale(self, mock_fs, client):
        """Company with no completed updates at all should be stale."""
        company = _make_company("c1", "Never Updated Co", "monthly")
        mock_fs.list_companies = AsyncMock(return_value=[company])

        # Only a pending update, no completed ones
        pending = _make_update(status="pending", days_ago=5)
        mock_fs.list_updates = AsyncMock(return_value=[pending])

        mock_task = MagicMock()
        mock_task.id = "task-3"
        mock_fs.create_task = AsyncMock(return_value=mock_task)

        response = client.post("/api/v1/internal/staleness-check?fund_id=f1")

        assert response.status_code == 200
        assert response.json()["tasks_created"] == 1

    @patch("app.routers.tasks.firestore_service")
    def test_no_updates_at_all_is_stale(self, mock_fs, client):
        """Company with zero updates should be stale."""
        company = _make_company("c1", "Brand New Co", "monthly")
        mock_fs.list_companies = AsyncMock(return_value=[company])
        mock_fs.list_updates = AsyncMock(return_value=[])

        mock_task = MagicMock()
        mock_task.id = "task-4"
        mock_fs.create_task = AsyncMock(return_value=mock_task)

        response = client.post("/api/v1/internal/staleness-check?fund_id=f1")

        assert response.status_code == 200
        assert response.json()["tasks_created"] == 1

    @patch("app.routers.tasks.firestore_service")
    def test_unknown_frequency_uses_default(self, mock_fs, client):
        """Unknown frequency should fall back to 60-day default."""
        company = _make_company("c1", "Custom Freq Co", "biweekly")
        mock_fs.list_companies = AsyncMock(return_value=[company])

        # 65 days > 60 default
        update = _make_update(status="completed", days_ago=65)
        mock_fs.list_updates = AsyncMock(return_value=[update])

        mock_task = MagicMock()
        mock_task.id = "task-5"
        mock_fs.create_task = AsyncMock(return_value=mock_task)

        response = client.post("/api/v1/internal/staleness-check?fund_id=f1")

        assert response.status_code == 200
        assert response.json()["tasks_created"] == 1

    @patch("app.routers.tasks.firestore_service")
    def test_multiple_companies_mixed(self, mock_fs, client):
        """Mix of stale and fresh companies."""
        fresh = _make_company("c1", "Fresh Co", "monthly")
        stale = _make_company("c2", "Stale Co", "monthly")
        mock_fs.list_companies = AsyncMock(return_value=[fresh, stale])

        # Fresh: 10 days ago, Stale: 50 days ago
        async def mock_list_updates(fund_id, company_id, limit):
            if company_id == "c1":
                return [_make_update("completed", 10)]
            return [_make_update("completed", 50)]

        mock_fs.list_updates = AsyncMock(side_effect=mock_list_updates)

        mock_task = MagicMock()
        mock_task.id = "task-6"
        mock_fs.create_task = AsyncMock(return_value=mock_task)

        response = client.post("/api/v1/internal/staleness-check?fund_id=f1")

        assert response.status_code == 200
        data = response.json()
        assert data["tasks_created"] == 1  # Only the stale one
        assert data["companies_checked"] == 2

    @patch("app.routers.tasks.firestore_service")
    def test_task_description_includes_reason(self, mock_fs, client):
        """Created task should include the staleness reason."""
        company = _make_company("c1", "Stale Co", "monthly")
        mock_fs.list_companies = AsyncMock(return_value=[company])

        update = _make_update(status="completed", days_ago=40)
        mock_fs.list_updates = AsyncMock(return_value=[update])

        mock_task = MagicMock()
        mock_task.id = "task-7"
        mock_fs.create_task = AsyncMock(return_value=mock_task)

        response = client.post("/api/v1/internal/staleness-check?fund_id=f1")

        assert response.status_code == 200
        # Verify the task description contains staleness info
        call_args = mock_fs.create_task.call_args[0][0]
        assert "Stale data" in call_args.description
        assert "40 days" in call_args.description
        assert call_args.priority.value == "high"
