"""Company CRUD endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import verify_api_key
from app.models.company import Company, CompanyCreate, CompanyUpdate
from app.services.firestore import firestore_service

router = APIRouter(
    prefix="/api/v1/companies",
    tags=["companies"],
    dependencies=[Depends(verify_api_key)],
)


@router.get("", response_model=list[Company])
async def list_companies(fund_id: str) -> list[Company]:
    """List all portfolio companies for a fund."""
    return await firestore_service.list_companies(fund_id)


@router.get("/{company_id}", response_model=Company)
async def get_company(company_id: str) -> Company:
    """Get a single company by ID."""
    company = await firestore_service.get_company(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


@router.post("", response_model=Company, status_code=201)
async def create_company(data: CompanyCreate) -> Company:
    """Register a new portfolio company."""
    return await firestore_service.create_company(data)


@router.put("/{company_id}", response_model=Company)
async def update_company(company_id: str, data: CompanyUpdate) -> Company:
    """Update company settings, mapping instructions, etc."""
    company = await firestore_service.update_company(company_id, data)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company
