"""Pydantic models for the tasks collection."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):  # noqa: UP042  # noqa: UP042
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class TaskPriority(str, Enum):  # noqa: UP042  # noqa: UP042
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaskCreate(BaseModel):
    """Request model for creating a task."""

    fund_id: str
    company_id: str
    source_update_id: str = ""
    description: str = Field(..., min_length=1)
    due_date: datetime | None = None
    priority: TaskPriority = TaskPriority.MEDIUM
    assigned_to: str = ""


class TaskUpdate(BaseModel):
    """Request model for updating a task."""

    description: str | None = None
    due_date: datetime | None = None
    priority: TaskPriority | None = None
    status: TaskStatus | None = None
    assigned_to: str | None = None


class Task(BaseModel):
    """Full task entity as stored in Firestore."""

    id: str
    fund_id: str
    company_id: str
    source_update_id: str = ""
    description: str
    due_date: datetime | None = None
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.PENDING
    assigned_to: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
