"""Ingestion endpoints — file upload and (later) email ingestion."""

import os
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.config import settings
from app.dependencies import verify_api_key
from app.models.update import SourceFileType, SourceType, Update, UpdateCreate
from app.services.firestore import firestore_service
from app.services.storage import storage_service

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
    with status=pending. Processing is triggered by the GCS event.
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

    # Upload to GCS
    gcs_path = await storage_service.upload_raw_file(
        fund_id=fund_id,
        company_id=company_id,
        filename=file.filename,
        contents=contents,
        content_type=file.content_type or "application/octet-stream",
    )

    # Create update record
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
    return update


@router.post("/email", response_model=Update, status_code=201)
async def ingest_email() -> Update:
    """Receive email content from the email watcher (Phase 3).

    Placeholder — will accept parsed email body, subject, sender, and attachments.
    """
    raise HTTPException(status_code=501, detail="Email ingestion not yet implemented (Phase 3)")
