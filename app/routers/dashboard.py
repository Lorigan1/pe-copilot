"""Dashboard API endpoints — the portfolio-level aggregated view."""

from fastapi import APIRouter, Depends

from app.dependencies import verify_api_key
from app.models.dashboard import PortfolioView
from app.services.firestore import firestore_service

router = APIRouter(
    prefix="/api/v1/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(verify_api_key)],
)


@router.get("/portfolio", response_model=PortfolioView)
async def portfolio_dashboard(fund_id: str) -> PortfolioView:
    """Get the aggregated portfolio dashboard view.

    Returns all companies with their latest metrics, health status,
    and summaries — everything the comptroller needs at a glance.
    """
    return await firestore_service.get_portfolio_view(fund_id)
