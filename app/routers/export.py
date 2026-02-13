"""Export endpoints — Google Sheets and PDF generation."""

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import verify_api_key

router = APIRouter(
    prefix="/api/v1/export",
    tags=["export"],
    dependencies=[Depends(verify_api_key)],
)


@router.post("/sheets/{company_id}")
async def export_to_sheets(company_id: str) -> dict:
    """Push latest normalised metrics to a Google Sheet.

    Implemented in Phase 7.
    """
    raise HTTPException(status_code=501, detail="Sheets export not yet implemented (Phase 7)")


@router.post("/pdf/{digest_id}")
async def export_to_pdf(digest_id: str) -> dict:
    """Generate an LP-ready PDF report for a digest.

    Implemented in Phase 7.
    """
    raise HTTPException(status_code=501, detail="PDF export not yet implemented (Phase 7)")
