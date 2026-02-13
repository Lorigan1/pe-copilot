"""Firestore service — CRUD operations for all collections.

In local dev, this can be pointed at the Firestore emulator by setting
FIRESTORE_EMULATOR_HOST=localhost:8080 in your environment.
"""

from datetime import datetime
from typing import Any

from app.config import settings
from app.models.company import Company, CompanyCreate, CompanyUpdate
from app.models.fund import Fund, FundCreate, FundUpdate
from app.models.task import Task, TaskCreate, TaskStatus, TaskUpdate
from app.models.update import ProcessingStatus, Update, UpdateCreate
from app.models.dashboard import CompanySnapshot, PortfolioView


class FirestoreService:
    """Handles all Firestore reads and writes.

    Initialised lazily — the Firestore client is only created when first needed.
    This avoids import-time failures when running tests without GCP credentials.
    """

    def __init__(self) -> None:
        self._client: Any | None = None

    @property
    def client(self) -> Any:
        """Lazy-init the Firestore client."""
        if self._client is None:
            from google.cloud import firestore

            self._client = firestore.AsyncClient(
                project=settings.gcp_project_id or None,
                database=settings.firestore_database,
            )
        return self._client

    # ─── Funds ────────────────────────────────────────────────

    async def create_fund(self, data: FundCreate) -> Fund:
        """Create a new fund."""
        doc_ref = self.client.collection("funds").document()
        fund = Fund(id=doc_ref.id, **data.model_dump())
        await doc_ref.set(fund.model_dump())
        return fund

    async def get_fund(self, fund_id: str) -> Fund | None:
        """Get a fund by ID."""
        doc = await self.client.collection("funds").document(fund_id).get()
        if not doc.exists:
            return None
        return Fund(**doc.to_dict())

    async def update_fund(self, fund_id: str, data: FundUpdate) -> Fund | None:
        """Update a fund."""
        doc_ref = self.client.collection("funds").document(fund_id)
        doc = await doc_ref.get()
        if not doc.exists:
            return None
        updates = {k: v for k, v in data.model_dump().items() if v is not None}
        await doc_ref.update(updates)
        updated_doc = await doc_ref.get()
        return Fund(**updated_doc.to_dict())

    # ─── Companies ────────────────────────────────────────────

    async def list_companies(self, fund_id: str) -> list[Company]:
        """List all companies for a fund."""
        query = self.client.collection("companies").where("fund_id", "==", fund_id)
        docs = query.stream()
        companies = []
        async for doc in docs:
            companies.append(Company(**doc.to_dict()))
        return companies

    async def get_company(self, company_id: str) -> Company | None:
        """Get a company by ID."""
        doc = await self.client.collection("companies").document(company_id).get()
        if not doc.exists:
            return None
        return Company(**doc.to_dict())

    async def create_company(self, data: CompanyCreate) -> Company:
        """Create a new portfolio company."""
        doc_ref = self.client.collection("companies").document()
        company = Company(id=doc_ref.id, **data.model_dump())
        await doc_ref.set(company.model_dump())
        return company

    async def update_company(self, company_id: str, data: CompanyUpdate) -> Company | None:
        """Update a company."""
        doc_ref = self.client.collection("companies").document(company_id)
        doc = await doc_ref.get()
        if not doc.exists:
            return None
        updates = {k: v for k, v in data.model_dump().items() if v is not None}
        await doc_ref.update(updates)
        updated_doc = await doc_ref.get()
        return Company(**updated_doc.to_dict())

    # ─── Updates ──────────────────────────────────────────────

    async def create_update(self, data: UpdateCreate) -> Update:
        """Create a new update record (status=pending)."""
        doc_ref = self.client.collection("updates").document()
        update = Update(
            id=doc_ref.id,
            **data.model_dump(),
            processing_status=ProcessingStatus.PENDING,
        )
        await doc_ref.set(update.model_dump())
        return update

    async def get_update(self, update_id: str) -> Update | None:
        """Get an update by ID."""
        doc = await self.client.collection("updates").document(update_id).get()
        if not doc.exists:
            return None
        return Update(**doc.to_dict())

    async def save_update(self, update: Update) -> Update:
        """Save a fully-populated update (after processing)."""
        doc_ref = self.client.collection("updates").document(update.id)
        await doc_ref.set(update.model_dump())
        return update

    async def list_updates(
        self, fund_id: str, company_id: str | None = None, limit: int = 50
    ) -> list[Update]:
        """List updates for a fund, optionally filtered by company."""
        query = self.client.collection("updates").where("fund_id", "==", fund_id)
        if company_id:
            query = query.where("company_id", "==", company_id)
        query = query.order_by("received_at", direction="DESCENDING").limit(limit)
        docs = query.stream()
        updates = []
        async for doc in docs:
            updates.append(Update(**doc.to_dict()))
        return updates

    async def get_previous_update(self, company_id: str, before_id: str) -> Update | None:
        """Get the most recent completed update before a given one."""
        query = (
            self.client.collection("updates")
            .where("company_id", "==", company_id)
            .where("processing_status", "==", ProcessingStatus.COMPLETED)
            .order_by("received_at", direction="DESCENDING")
            .limit(2)
        )
        docs = query.stream()
        async for doc in docs:
            data = doc.to_dict()
            if data.get("id") != before_id:
                return Update(**data)
        return None

    async def mark_update_reviewed(self, update_id: str, reviewer_email: str) -> Update:
        """Mark a needs_review update as reviewed."""
        doc_ref = self.client.collection("updates").document(update_id)
        await doc_ref.update({
            "processing_status": ProcessingStatus.COMPLETED,
            "reviewed_by": reviewer_email,
            "reviewed_at": datetime.utcnow(),
        })
        doc = await doc_ref.get()
        return Update(**doc.to_dict())

    # ─── Tasks ────────────────────────────────────────────────

    async def list_tasks(
        self,
        fund_id: str,
        company_id: str | None = None,
        status: str | None = None,
        assigned_to: str | None = None,
    ) -> list[Task]:
        """List tasks with optional filters."""
        query = self.client.collection("tasks").where("fund_id", "==", fund_id)
        if company_id:
            query = query.where("company_id", "==", company_id)
        if status:
            query = query.where("status", "==", status)
        if assigned_to:
            query = query.where("assigned_to", "==", assigned_to)
        docs = query.stream()
        tasks = []
        async for doc in docs:
            tasks.append(Task(**doc.to_dict()))
        return tasks

    async def create_task(self, data: TaskCreate) -> Task:
        """Create a new task."""
        doc_ref = self.client.collection("tasks").document()
        task = Task(id=doc_ref.id, **data.model_dump())
        await doc_ref.set(task.model_dump())
        return task

    async def update_task(self, task_id: str, data: TaskUpdate) -> Task | None:
        """Update a task."""
        doc_ref = self.client.collection("tasks").document(task_id)
        doc = await doc_ref.get()
        if not doc.exists:
            return None
        updates = {k: v for k, v in data.model_dump().items() if v is not None}
        if updates.get("status") == TaskStatus.DONE:
            updates["completed_at"] = datetime.utcnow()
        await doc_ref.update(updates)
        updated_doc = await doc_ref.get()
        return Task(**updated_doc.to_dict())

    async def count_pending_tasks(self, company_id: str) -> int:
        """Count pending tasks for a company."""
        query = (
            self.client.collection("tasks")
            .where("company_id", "==", company_id)
            .where("status", "in", [TaskStatus.PENDING, TaskStatus.IN_PROGRESS])
        )
        count = 0
        async for _ in query.stream():
            count += 1
        return count

    # ─── Dashboard ────────────────────────────────────────────

    async def get_portfolio_view(self, fund_id: str) -> PortfolioView:
        """Build the full portfolio dashboard view."""
        fund = await self.get_fund(fund_id)
        if not fund:
            return PortfolioView(
                fund_id=fund_id,
                fund_name="Unknown",
                total_companies=0,
                companies_green=0,
                companies_amber=0,
                companies_red=0,
                companies=[],
            )

        companies = await self.list_companies(fund_id)
        snapshots: list[CompanySnapshot] = []

        for company in companies:
            # Get latest completed update
            updates = await self.list_updates(fund_id, company.id, limit=1)
            latest = updates[0] if updates else None
            pending_tasks = await self.count_pending_tasks(company.id)

            snapshots.append(CompanySnapshot(
                id=company.id,
                name=company.name,
                sector=company.sector,
                health_status=company.health_status,
                health_reasons=company.health_reasons,
                last_update_at=company.last_update_at.isoformat() if company.last_update_at else None,
                latest_period=latest.metrics_period if latest else "",
                latest_metrics=latest.normalised_metrics if latest else {},
                latest_summary=latest.llm_summary if latest else "",
                latest_risks=latest.llm_risks if latest else [],
                pending_tasks=pending_tasks,
            ))

        green = sum(1 for s in snapshots if s.health_status == "green")
        amber = sum(1 for s in snapshots if s.health_status == "amber")
        red = sum(1 for s in snapshots if s.health_status == "red")

        return PortfolioView(
            fund_id=fund_id,
            fund_name=fund.name,
            total_companies=len(companies),
            companies_green=green,
            companies_amber=amber,
            companies_red=red,
            companies=snapshots,
        )


# Singleton — import this throughout the app
firestore_service = FirestoreService()
