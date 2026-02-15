"""Cloud Storage service — file upload, download, signed URLs, and deletion.

Includes retry logic with exponential backoff, integrity verification,
and structured logging for production reliability.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

from google.api_core import exceptions as gcp_exceptions
from google.api_core import retry as gcp_retry

from app.config import settings

logger = logging.getLogger(__name__)


# ─── Custom Exceptions ───


class StorageError(Exception):
    """Base exception for Cloud Storage operations."""

    def __init__(self, message: str, bucket: str = "", blob_path: str = "") -> None:
        self.bucket = bucket
        self.blob_path = blob_path
        super().__init__(message)


class StorageUploadError(StorageError):
    """Raised when a file upload fails or integrity check fails."""


class StorageDownloadError(StorageError):
    """Raised when a file download fails."""


# ─── Retry Configuration ───

# Retry on transient GCP errors: 503 Service Unavailable, timeouts, connection issues
_RETRY_PREDICATE = gcp_retry.if_exception_type(
    ConnectionError,
    TimeoutError,
    gcp_exceptions.ServiceUnavailable,
    gcp_exceptions.TooManyRequests,
    gcp_exceptions.InternalServerError,
)

_RETRY_CONFIG = gcp_retry.Retry(
    predicate=_RETRY_PREDICATE,
    initial=1.0,       # 1 second initial delay
    maximum=32.0,       # Max 32 seconds between retries
    multiplier=2.0,     # Double the delay each time
    deadline=180.0,     # Give up after 3 minutes total
)


class StorageService:
    """Handles all Cloud Storage operations with retry and logging."""

    def __init__(self) -> None:
        self._client: Any | None = None

    @property
    def client(self) -> Any:
        """Lazy-init the GCS client."""
        if self._client is None:
            from google.cloud import storage

            self._client = storage.Client(project=settings.gcp_project_id or None)
        return self._client

    # ─── Helpers ───

    def _parse_gcs_url(self, gcs_url: str) -> tuple[str, str]:
        """Parse a gs://bucket/path URL into (bucket_name, blob_path)."""
        if not gcs_url.startswith("gs://"):
            raise ValueError(f"Invalid GCS URL: {gcs_url}")
        parts = gcs_url[5:].split("/", 1)
        bucket_name = parts[0]
        blob_path = parts[1] if len(parts) > 1 else ""
        return bucket_name, blob_path

    # ─── Upload ───

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

        Raises StorageUploadError if the upload or integrity check fails.
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        blob_path = f"{fund_id}/{company_id}/{timestamp}_{filename}"
        bucket_name = settings.gcs_raw_uploads_bucket
        size_kb = len(contents) / 1024

        logger.info(
            "Uploading %.1f KB to gs://%s/%s",
            size_kb, bucket_name, blob_path,
        )

        try:
            bucket = self.client.bucket(bucket_name)
            blob = bucket.blob(blob_path)
            blob.upload_from_string(
                contents,
                content_type=content_type,
                retry=_RETRY_CONFIG,
            )

            # Verify the blob was actually persisted
            blob.reload()
            if not blob.exists():
                raise StorageUploadError(
                    f"Upload succeeded but blob not found on verification: {blob_path}",
                    bucket=bucket_name,
                    blob_path=blob_path,
                )

            gcs_url = f"gs://{bucket_name}/{blob_path}"
            logger.info("Upload complete: %s (%d bytes)", gcs_url, blob.size or 0)
            return gcs_url

        except StorageUploadError:
            raise
        except Exception as exc:
            logger.error(
                "Upload failed for gs://%s/%s: %s",
                bucket_name, blob_path, exc,
            )
            raise StorageUploadError(
                f"Failed to upload file: {exc}",
                bucket=bucket_name,
                blob_path=blob_path,
            ) from exc

    # ─── Download ───

    async def download_file(self, gcs_url: str) -> bytes:
        """Download a file from GCS given its gs:// URL.

        Raises StorageDownloadError if the blob doesn't exist or download fails.
        """
        bucket_name, blob_path = self._parse_gcs_url(gcs_url)

        logger.info("Downloading gs://%s/%s", bucket_name, blob_path)

        try:
            bucket = self.client.bucket(bucket_name)
            blob = bucket.blob(blob_path)

            if not blob.exists():
                raise StorageDownloadError(
                    f"Blob not found: gs://{bucket_name}/{blob_path}",
                    bucket=bucket_name,
                    blob_path=blob_path,
                )

            data = blob.download_as_bytes(retry=_RETRY_CONFIG)
            logger.info(
                "Download complete: gs://%s/%s (%d bytes)",
                bucket_name, blob_path, len(data),
            )
            return data

        except StorageDownloadError:
            raise
        except Exception as exc:
            logger.error(
                "Download failed for gs://%s/%s: %s",
                bucket_name, blob_path, exc,
            )
            raise StorageDownloadError(
                f"Failed to download file: {exc}",
                bucket=bucket_name,
                blob_path=blob_path,
            ) from exc

    # ─── Signed URLs ───

    async def generate_signed_url(self, gcs_url: str, expiry_hours: int = 1) -> str:
        """Generate a signed URL for temporary access to a file."""
        bucket_name, blob_path = self._parse_gcs_url(gcs_url)

        logger.debug(
            "Generating signed URL for gs://%s/%s (expiry: %dh)",
            bucket_name, blob_path, expiry_hours,
        )

        try:
            bucket = self.client.bucket(bucket_name)
            blob = bucket.blob(blob_path)
            url = blob.generate_signed_url(
                expiration=timedelta(hours=expiry_hours),
                method="GET",
            )
            logger.debug("Signed URL generated for gs://%s/%s", bucket_name, blob_path)
            return url

        except Exception as exc:
            logger.error(
                "Signed URL generation failed for gs://%s/%s: %s",
                bucket_name, blob_path, exc,
            )
            raise StorageError(
                f"Failed to generate signed URL: {exc}",
                bucket=bucket_name,
                blob_path=blob_path,
            ) from exc

    # ─── Reports ───

    async def upload_report(
        self,
        fund_id: str,
        filename: str,
        contents: bytes,
        content_type: str,
    ) -> str:
        """Upload a generated report (PDF, etc.) to the reports bucket.

        Raises StorageUploadError if the upload fails.
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        blob_path = f"{fund_id}/reports/{timestamp}_{filename}"
        bucket_name = settings.gcs_reports_bucket
        size_kb = len(contents) / 1024

        logger.info(
            "Uploading report (%.1f KB) to gs://%s/%s",
            size_kb, bucket_name, blob_path,
        )

        try:
            bucket = self.client.bucket(bucket_name)
            blob = bucket.blob(blob_path)
            blob.upload_from_string(
                contents,
                content_type=content_type,
                retry=_RETRY_CONFIG,
            )

            gcs_url = f"gs://{bucket_name}/{blob_path}"
            logger.info("Report upload complete: %s", gcs_url)
            return gcs_url

        except Exception as exc:
            logger.error(
                "Report upload failed for gs://%s/%s: %s",
                bucket_name, blob_path, exc,
            )
            raise StorageUploadError(
                f"Failed to upload report: {exc}",
                bucket=bucket_name,
                blob_path=blob_path,
            ) from exc

    # ─── Deletion (for transaction cleanup) ───

    async def delete_file(self, gcs_url: str) -> None:
        """Delete a file from GCS. Used for cleanup when downstream steps fail.

        Silently ignores if the blob doesn't exist (already cleaned up).
        """
        bucket_name, blob_path = self._parse_gcs_url(gcs_url)

        logger.info("Deleting gs://%s/%s", bucket_name, blob_path)

        try:
            bucket = self.client.bucket(bucket_name)
            blob = bucket.blob(blob_path)
            blob.delete(retry=_RETRY_CONFIG)
            logger.info("Deleted gs://%s/%s", bucket_name, blob_path)

        except gcp_exceptions.NotFound:
            logger.warning(
                "Blob already deleted or not found: gs://%s/%s",
                bucket_name, blob_path,
            )

        except Exception as exc:
            logger.error(
                "Failed to delete gs://%s/%s: %s",
                bucket_name, blob_path, exc,
            )
            raise StorageError(
                f"Failed to delete file: {exc}",
                bucket=bucket_name,
                blob_path=blob_path,
            ) from exc


# Singleton
storage_service = StorageService()
