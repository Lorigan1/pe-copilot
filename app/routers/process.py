"""Processing endpoints — trigger normalisation of an uploaded file."""

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import verify_api_key
from app.models.update import ProcessingStatus, Update
from app.services.firestore import firestore_service
from app.services.normaliser import normaliser_service

router = APIRouter(
    prefix="/api/v1/process",
    tags=["processing"],
    dependencies=[Depends(verify_api_key)],
)


@router.get("/{update_id}/status", response_model=Update)
async def get_update_status(update_id: str) -> Update:
    """Get the current processing status of an update.

    Used by the upload form to poll for completion after Pub/Sub triggers processing.
    """
    update = await firestore_service.get_update(update_id)
    if not update:
        raise HTTPException(status_code=404, detail="Update not found")
    return update


@router.post("/{update_id}", response_model=Update)
async def process_update(update_id: str) -> Update:
    """Trigger the normalisation pipeline for a pending update.

    Pipeline:
    1. Download file from GCS
    2. Extract text/tables (Layer 1: deterministic parsing)
    3. Normalise via Claude (Layer 2: LLM)
    4. Validate and store (Layer 3: Pydantic + variance calc)
    """
    update = await firestore_service.get_update(update_id)
    if not update:
        raise HTTPException(status_code=404, detail="Update not found")

    if update.processing_status not in (ProcessingStatus.PENDING, ProcessingStatus.FAILED):
        raise HTTPException(
            status_code=400,
            detail=f"Update is already {update.processing_status}. Cannot reprocess.",
        )

    # Run the normalisation pipeline
    processed = await normaliser_service.process_update(update)
    return processed


@router.post("/{update_id}/review", response_model=Update)
async def review_update(update_id: str, reviewer_email: str = "") -> Update:
    """Mark a needs_review update as reviewed/approved.

    The comptroller checks the normalised data and confirms it's correct.
    """
    update = await firestore_service.get_update(update_id)
    if not update:
        raise HTTPException(status_code=404, detail="Update not found")

    if update.processing_status != ProcessingStatus.NEEDS_REVIEW:
        raise HTTPException(
            status_code=400,
            detail=f"Update is {update.processing_status}, not needs_review.",
        )

    reviewed = await firestore_service.mark_update_reviewed(update_id, reviewer_email)
    return reviewed
