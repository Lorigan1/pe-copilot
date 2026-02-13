"""Task management endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import verify_api_key
from app.models.task import Task, TaskCreate, TaskUpdate
from app.services.firestore import firestore_service

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
