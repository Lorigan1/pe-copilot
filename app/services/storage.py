"""Cloud Storage service — file upload, download, and signed URL generation."""

from datetime import datetime, timedelta
from typing import Any

from app.config import settings


class StorageService:
    """Handles all Cloud Storage operations."""

    def __init__(self) -> None:
        self._client: Any | None = None

    @property
    def client(self) -> Any:
        """Lazy-init the GCS client."""
        if self._client is None:
            from google.cloud import storage

            self._client = storage.Client(project=settings.gcp_project_id or None)
        return self._client

    async def upload_raw_file(
        self,
        fund_id: str,
        company_id: str,
        filename: str,
        contents: bytes,
        content_type: str,
    ) -> str:
        """Upload a raw file to the uploads bucket.

        Path structure: {fund_id}/{company_id}/{timestamp}_{filename}
        Returns the full GCS path (gs://bucket/path).
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        blob_path = f"{fund_id}/{company_id}/{timestamp}_{filename}"

        bucket = self.client.bucket(settings.gcs_raw_uploads_bucket)
        blob = bucket.blob(blob_path)
        blob.upload_from_string(contents, content_type=content_type)

        return f"gs://{settings.gcs_raw_uploads_bucket}/{blob_path}"

    async def download_file(self, gcs_url: str) -> bytes:
        """Download a file from GCS given its gs:// URL."""
        # Parse gs://bucket/path
        if not gcs_url.startswith("gs://"):
            raise ValueError(f"Invalid GCS URL: {gcs_url}")
        parts = gcs_url[5:].split("/", 1)
        bucket_name = parts[0]
        blob_path = parts[1] if len(parts) > 1 else ""

        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        return blob.download_as_bytes()

    async def generate_signed_url(self, gcs_url: str, expiry_hours: int = 1) -> str:
        """Generate a signed URL for temporary access to a file."""
        if not gcs_url.startswith("gs://"):
            raise ValueError(f"Invalid GCS URL: {gcs_url}")
        parts = gcs_url[5:].split("/", 1)
        bucket_name = parts[0]
        blob_path = parts[1] if len(parts) > 1 else ""

        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        return blob.generate_signed_url(
            expiration=timedelta(hours=expiry_hours),
            method="GET",
        )

    async def upload_report(
        self,
        fund_id: str,
        filename: str,
        contents: bytes,
        content_type: str,
    ) -> str:
        """Upload a generated report (PDF, etc.) to the reports bucket."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        blob_path = f"{fund_id}/reports/{timestamp}_{filename}"

        bucket = self.client.bucket(settings.gcs_reports_bucket)
        blob = bucket.blob(blob_path)
        blob.upload_from_string(contents, content_type=content_type)

        return f"gs://{settings.gcs_reports_bucket}/{blob_path}"


# Singleton
storage_service = StorageService()
