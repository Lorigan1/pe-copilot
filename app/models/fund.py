"""Pydantic models for the funds collection."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class FundSettings(BaseModel):
    """Fund-level configuration."""

    digest_frequency: str = "weekly"  # weekly | monthly
    staleness_amber_days: int = 21
    staleness_red_days: int = 45
    default_variance_threshold: float = 0.20  # 20% change triggers alert


class FundCreate(BaseModel):
    """Request model for creating a new fund."""

    name: str = Field(..., min_length=1, max_length=200)
    manager_name: str = Field(..., min_length=1, max_length=200)
    manager_email: str = Field(..., min_length=1)
    settings: FundSettings = FundSettings()


class FundUpdate(BaseModel):
    """Request model for updating a fund."""

    name: str | None = None
    manager_name: str | None = None
    manager_email: str | None = None
    settings: FundSettings | None = None


class Fund(BaseModel):
    """Full fund entity as stored in Firestore."""

    id: str
    name: str
    manager_name: str
    manager_email: str
    settings: FundSettings = FundSettings()
    created_at: datetime = Field(default_factory=datetime.utcnow)
