"""File download endpoint — generates signed URLs for original uploads."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import verify_api_key
from app.services.storage import storage_service

router = APIRouter(
    prefix="/api/v1/files",
    tags=["files"],
    dependencies=[Depends(verify_api_key)],
)


@router.get("/download")
async def get_download_url(
    gcs_url: str = Query(..., description="GCS path (gs://bucket/path)"),
) -> dict:
    """Generate a time-limited signed URL for downloading an original file.

    Returns a 1-hour signed URL that allows direct download without auth.
    """
    if not gcs_url.startswith("gs://"):
        raise HTTPException(status_code=400, detail="Invalid GCS URL format")

    try:
        signed_url = await storage_service.generate_signed_url(gcs_url, expiry_hours=1)
        return {"download_url": signed_url, "expires_in": "1 hour"}
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate download URL: {exc}",
        ) from exc
