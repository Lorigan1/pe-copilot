"""Tests for the hardened Cloud Storage service."""

import pytest

from app.services.storage import (
    StorageDownloadError,
    StorageError,
    StorageService,
    StorageUploadError,
)


# ─── Custom Exceptions ───


class TestStorageExceptions:
    """Verify custom exception hierarchy and attributes."""

    def test_storage_error_has_bucket_and_blob(self):
        exc = StorageError("test", bucket="my-bucket", blob_path="path/file.pdf")
        assert exc.bucket == "my-bucket"
        assert exc.blob_path == "path/file.pdf"
        assert str(exc) == "test"

    def test_storage_error_defaults(self):
        exc = StorageError("bare error")
        assert exc.bucket == ""
        assert exc.blob_path == ""

    def test_upload_error_is_storage_error(self):
        exc = StorageUploadError("upload failed", bucket="b", blob_path="p")
        assert isinstance(exc, StorageError)
        assert isinstance(exc, Exception)

    def test_download_error_is_storage_error(self):
        exc = StorageDownloadError("download failed", bucket="b", blob_path="p")
        assert isinstance(exc, StorageError)
        assert isinstance(exc, Exception)


# ─── URL Parsing ───


class TestParseGcsUrl:
    """Verify gs:// URL parsing helper."""

    def setup_method(self):
        self.svc = StorageService()

    def test_valid_url(self):
        bucket, path = self.svc._parse_gcs_url("gs://my-bucket/fund/company/file.pdf")
        assert bucket == "my-bucket"
        assert path == "fund/company/file.pdf"

    def test_url_with_nested_path(self):
        bucket, path = self.svc._parse_gcs_url("gs://uploads/a/b/c/d/file.xlsx")
        assert bucket == "uploads"
        assert path == "a/b/c/d/file.xlsx"

    def test_url_bucket_only(self):
        bucket, path = self.svc._parse_gcs_url("gs://my-bucket")
        assert bucket == "my-bucket"
        assert path == ""

    def test_url_bucket_with_slash(self):
        bucket, path = self.svc._parse_gcs_url("gs://my-bucket/")
        assert bucket == "my-bucket"
        assert path == ""

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError, match="Invalid GCS URL"):
            self.svc._parse_gcs_url("https://storage.googleapis.com/bucket/path")

    def test_empty_url_raises(self):
        with pytest.raises(ValueError, match="Invalid GCS URL"):
            self.svc._parse_gcs_url("")

    def test_s3_url_raises(self):
        with pytest.raises(ValueError, match="Invalid GCS URL"):
            self.svc._parse_gcs_url("s3://bucket/path")


# ─── Retry Configuration ───


class TestRetryConfig:
    """Verify retry configuration is properly defined."""

    def test_retry_config_exists(self):
        from app.services.storage import _RETRY_CONFIG

        assert _RETRY_CONFIG is not None

    def test_retry_predicate_exists(self):
        from app.services.storage import _RETRY_PREDICATE

        assert _RETRY_PREDICATE is not None

    def test_retry_initial_delay(self):
        from app.services.storage import _RETRY_CONFIG

        assert _RETRY_CONFIG._initial == 1.0

    def test_retry_max_delay(self):
        from app.services.storage import _RETRY_CONFIG

        assert _RETRY_CONFIG._maximum == 32.0

    def test_retry_multiplier(self):
        from app.services.storage import _RETRY_CONFIG

        assert _RETRY_CONFIG._multiplier == 2.0
