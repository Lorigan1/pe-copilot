"""PE CoPilot — FastAPI application entry point."""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import companies, dashboard, digest, export, files, ingest, process, tasks

# ─── Logging ───
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# ─── App ───
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Financial data normalisation engine for private equity fund management. "
        "Ingests heterogeneous financial data from portfolio companies and produces "
        "a unified, comparable view."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
)

# ─── Routers ───
app.include_router(companies.router)
app.include_router(ingest.router)
app.include_router(process.router)
app.include_router(tasks.router)
app.include_router(tasks.internal_router)
app.include_router(dashboard.router)
app.include_router(digest.router)
app.include_router(export.router)
app.include_router(files.router)

# ─── Static files (upload form + dashboard) ───
_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


# ─── Health check ───
@app.get("/health", tags=["system"])
async def health_check() -> dict:
    """Health check endpoint for Cloud Run liveness probes."""
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
    }


@app.get("/", tags=["system"])
async def root() -> dict:
    """Root endpoint — redirect info."""
    return {
        "app": settings.app_name,
        "docs": "/docs",
        "upload": "/static/upload.html",
        "dashboard": "/static/dashboard.html",
    }
