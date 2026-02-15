"""Task management endpoints and internal GCP endpoints.

The tasks router handles CRUD for manual task management.
The internal router handles Pub/Sub push callbacks and Cloud Scheduler jobs.
"""

import base64
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request

from app.dependencies import verify_api_key
from app.models.task import Task, TaskCreate, TaskPriority, TaskUpdate
from app.models.update import ProcessingStatus
from app.services.firestore import firestore_service
from app.services.normaliser import normaliser_service

logger = logging.getLogger(__name__)


# ─── Public Tasks Router (API-key authenticated) ───

router = APIRouter(
    prefix="/api/v1/tasks",
    tags=["tasks"],
    dependencies=[Depends(verify_api_key)],
)


@router.get("", response_model=list[Task])
async def list_tasks(
    fund_id: str,
    company_id: str | None = None,
    status: str | None = None,
    assigned_to: str | None = None,
) -> list[Task]:
    """List tasks, optionally filtered by company, status, or assignee."""
    return await firestore_service.list_tasks(
        fund_id=fund_id,
        company_id=company_id,
        status=status,
        assigned_to=assigned_to,
    )


@router.post("", response_model=Task, status_code=201)
async def create_task(data: TaskCreate) -> Task:
    """Create a task manually."""
    return await firestore_service.create_task(data)


@router.put("/{task_id}", response_model=Task)
async def update_task(task_id: str, data: TaskUpdate) -> Task:
    """Update task status, priority, assignment, etc."""
    task = await firestore_service.update_task(task_id, data)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


# ─── Internal Router (for Pub/Sub and Cloud Scheduler callbacks) ───
# These endpoints are called by GCP services, not by users.
# In production, use Cloud Run's built-in IAM auth (OIDC tokens).
# For now, these are unauthenticated — rely on Cloud Run ingress settings.

internal_router = APIRouter(
    prefix="/api/v1/internal",
    tags=["internal"],
)


@internal_router.post("/process-event")
async def process_event(request: Request) -> dict:
    """Handle Pub/Sub push messages to trigger file processing.

    Pub/Sub sends a POST with body:
    {
        "message": {
            "data": "<base64-encoded JSON>",
            "messageId": "...",
            "publishTime": "..."
        },
        "subscription": "projects/.../subscriptions/..."
    }

    Returns 200 to acknowledge the message. Pub/Sub retries on non-2xx responses.
    """
    try:
        body = await request.json()
        message = body.get("message", {})
        data_b64 = message.get("data", "")

        if not data_b64:
            logger.error("Pub/Sub message has no data field: %s", body)
            # Return 200 to avoid infinite retries on bad messages
            return {"status": "error", "detail": "No data in message"}

        # Decode the base64 payload
        message_json = base64.b64decode(data_b64).decode("utf-8")
        message_data = json.loads(message_json)

        update_id = message_data.get("update_id")
        if not update_id:
            logger.error("No update_id in Pub/Sub message: %s", message_data)
            return {"status": "error", "detail": "Missing update_id"}

        logger.info(
            "Received Pub/Sub process event for update %s (message_id: %s)",
            update_id,
            message.get("messageId", "unknown"),
        )

        # Fetch the update from Firestore
        update = await firestore_service.get_update(update_id)
        if not update:
            logger.error("Update %s not found in Firestore", update_id)
            return {"status": "error", "detail": "Update not found"}

        # Only process if still PENDING or FAILED
        if update.processing_status not in (
            ProcessingStatus.PENDING,
            ProcessingStatus.FAILED,
        ):
            logger.info(
                "Update %s is already %s — skipping",
                update_id, update.processing_status,
            )
            return {"status": "skipped", "detail": f"Already {update.processing_status}"}

        # Run the normalisation pipeline
        processed = await normaliser_service.process_update(update)
        logger.info(
            "Processing complete for update %s — status: %s",
            update_id, processed.processing_status,
        )

        return {
            "status": "success",
            "update_id": update_id,
            "processing_status": processed.processing_status,
        }

    except Exception as exc:
        logger.exception("Error processing Pub/Sub event: %s", exc)
        # Return 500 so Pub/Sub retries
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ─── Staleness thresholds (days) by reporting frequency ───
_STALENESS_THRESHOLDS: dict[str, int] = {
    "monthly": 35,
    "quarterly": 100,
    "annually": 380,
    "varies": 60,
}
_DEFAULT_STALENESS_DAYS = 60


@internal_router.post("/staleness-check")
async def staleness_check(fund_id: str) -> dict:
    """Check all companies in a fund for stale updates and create tasks.

    Called by Cloud Scheduler on a daily cron.
    For each company, if the most recent completed update is older than
    the staleness threshold (based on reporting_frequency), a task is created.

    Args:
        fund_id: The fund ID to check. Required.

    Returns:
        Summary with tasks_created and companies_checked counts.
    """
    logger.info("Running staleness check for fund %s", fund_id)

    try:
        companies = await firestore_service.list_companies(fund_id)
        if not companies:
            logger.info("No companies found for fund %s", fund_id)
            return {"status": "success", "tasks_created": 0, "companies_checked": 0}

        tasks_created = 0

        for company in companies:
            # Determine threshold for this company
            threshold_days = _STALENESS_THRESHOLDS.get(
                company.reporting_frequency,
                _DEFAULT_STALENESS_DAYS,
            )

            # Get most recent updates for this company
            recent_updates = await firestore_service.list_updates(
                fund_id=fund_id,
                company_id=company.id,
                limit=5,
            )

            # Find the most recent completed update
            completed = [
                u for u in recent_updates
                if u.processing_status == ProcessingStatus.COMPLETED
            ]

            is_stale = False
            reason = ""

            if not completed:
                is_stale = True
                reason = f"No completed updates received for {company.name}"
            else:
                latest = completed[0]
                days_since = (datetime.utcnow() - latest.received_at).days
                if days_since > threshold_days:
                    is_stale = True
                    reason = (
                        f"No update for {days_since} days "
                        f"(threshold: {threshold_days}d for {company.reporting_frequency})"
                    )

            if is_stale:
                task = await firestore_service.create_task(
                    TaskCreate(
                        fund_id=fund_id,
                        company_id=company.id,
                        description=f"Stale data: {reason}",
                        priority=TaskPriority.HIGH,
                    )
                )
                logger.info(
                    "Created staleness task %s for company %s: %s",
                    task.id, company.id, reason,
                )
                tasks_created += 1

        logger.info(
            "Staleness check complete for fund %s: %d tasks created, %d companies checked",
            fund_id, tasks_created, len(companies),
        )

        return {
            "status": "success",
            "tasks_created": tasks_created,
            "companies_checked": len(companies),
        }

    except Exception as exc:
        logger.exception("Staleness check failed for fund %s: %s", fund_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
