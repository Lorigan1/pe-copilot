"""Digest generation and retrieval endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import verify_api_key

router = APIRouter(
    prefix="/api/v1/digest",
    tags=["digest"],
    dependencies=[Depends(verify_api_key)],
)


@router.post("/generate")
async def generate_digest(fund_id: str) -> dict:
    """Trigger generation of a portfolio digest.

    Called by the weekly Cloud Scheduler job.
    Implemented in Phase 7.
    """
    raise HTTPException(status_code=501, detail="Digest generation not yet implemented (Phase 7)")


@router.get("/latest")
async def get_latest_digest(fund_id: str) -> dict:
    """Get the most recently generated digest.

    Implemented in Phase 7.
    """
    raise HTTPException(status_code=501, detail="Digest retrieval not yet implemented (Phase 7)")
