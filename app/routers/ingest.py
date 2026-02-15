"""Ingestion endpoints — file upload and (later) email ingestion."""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.config import settings
from app.dependencies import verify_api_key
from app.models.update import SourceFileType, SourceType, Update, UpdateCreate
from app.services.firestore import firestore_service
from app.services.pubsub import pubsub_service
from app.services.storage import storage_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/ingest",
    tags=["ingestion"],
    dependencies=[Depends(verify_api_key)],
)

# Map file extensions to our source file types
EXTENSION_MAP: dict[str, SourceFileType] = {
    ".xlsx": SourceFileType.EXCEL,
    ".xls": SourceFileType.EXCEL,
    ".csv": SourceFileType.CSV,
    ".pdf": SourceFileType.PDF,
}


@router.post("/upload", response_model=Update, status_code=201)
async def upload_file(
    company_id: str = Form(...),
    fund_id: str = Form(...),
    period: str = Form(default=""),
    file: UploadFile = File(...),
) -> Update:
    """Upload a financial report file for processing.

    Accepts: .xlsx, .xls, .csv, .pdf
    The file is stored in GCS and an update record is created in Firestore
    with status=pending. Processing is triggered via Pub/Sub.
    """
    # Validate file extension
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    ext = Path(file.filename).suffix.lower()
    if ext not in settings.allowed_file_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' not allowed. Accepted: {settings.allowed_file_extensions}",
        )

    # Validate file size
    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > settings.max_upload_size_mb:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({size_mb:.1f}MB). Max: {settings.max_upload_size_mb}MB",
        )

    # ─── Step 1: Upload to GCS ───
    try:
        gcs_path = await storage_service.upload_raw_file(
            fund_id=fund_id,
            company_id=company_id,
            filename=file.filename,
            contents=contents,
            content_type=file.content_type or "application/octet-stream",
        )
        logger.info("File uploaded to GCS: %s", gcs_path)
    except Exception as exc:
        logger.error("GCS upload failed for %s: %s", file.filename, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload file to storage: {exc}",
        ) from exc

    # ─── Step 2: Create Firestore update record (with GCS cleanup on failure) ───
    try:
        source_file_type = EXTENSION_MAP.get(ext, SourceFileType.EXCEL)
        update_data = UpdateCreate(
            fund_id=fund_id,
            company_id=company_id,
            source_type=SourceType.MANUAL_UPLOAD,
            source_file_type=source_file_type,
            raw_file_urls=[gcs_path],
            metrics_period=period,
        )
        update = await firestore_service.create_update(update_data)
        logger.info("Firestore update record created: %s", update.id)

    except Exception as exc:
        # Transaction safety: clean up the GCS file if Firestore fails
        logger.error("Firestore create failed, cleaning up GCS file %s: %s", gcs_path, exc)
        try:
            await storage_service.delete_file(gcs_path)
        except Exception as cleanup_exc:
            logger.error("GCS cleanup also failed for %s: %s", gcs_path, cleanup_exc)

        raise HTTPException(
            status_code=500,
            detail=f"Failed to create update record: {exc}",
        ) from exc

    # ─── Step 3: Publish Pub/Sub event to trigger processing ───
    # Non-blocking: if Pub/Sub fails, the upload still succeeds.
    # The update stays PENDING and can be reprocessed manually.
    try:
        await pubsub_service.publish_file_ingestion_event(
            update_id=update.id,
            fund_id=fund_id,
            company_id=company_id,
        )
    except Exception as exc:
        logger.warning(
            "Pub/Sub publish failed for update %s (upload still succeeded, "
            "update is PENDING — reprocess manually if needed): %s",
            update.id, exc,
        )

    return update


@router.post("/email", response_model=Update, status_code=201)
async def ingest_email() -> Update:
    """Receive email content from the email watcher (Phase 3).

    Placeholder — will accept parsed email body, subject, sender, and attachments.
    """
    raise HTTPException(status_code=501, detail="Email ingestion not yet implemented (Phase 3)")
