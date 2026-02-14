"""
Application configuration. Loaded from environment variables with sensible defaults.
In production, secrets come from GCP Secret Manager. Locally, use a .env file.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ─── App ───
    app_name: str = "PE CoPilot"
    app_version: str = "0.1.0"
    debug: bool = False
    api_key: str = "dev-api-key-change-me"  # X-API-Key header for MVP auth

    # ─── GCP ───
    gcp_project_id: str = ""
    gcp_region: str = "europe-west2"

    # ─── Firestore ───
    firestore_database: str = "(default)"

    # ─── Cloud Storage ───
    gcs_raw_uploads_bucket: str = "pe-copilot-raw-uploads"
    gcs_reports_bucket: str = "pe-copilot-reports"

    # ─── Claude API ───
    anthropic_api_key: str = ""
    claude_model_normalisation: str = "claude-sonnet-4-5-20250929"
    claude_model_summarisation: str = "claude-sonnet-4-5-20250929"
    claude_model_fast: str = "claude-haiku-4-5-20251001"

    # ─── SendGrid ───
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = "noreply@pecopilot.com"

    # ─── File upload limits ───
    max_upload_size_mb: int = 25
    allowed_file_extensions: list[str] = [".xlsx", ".xls", ".csv", ".pdf"]

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


# Singleton instance — import this everywhere
settings = Settings()
