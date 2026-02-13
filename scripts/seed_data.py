"""Seed script — populate Firestore with test fund, companies, and metric schemas.

Usage:
    python -m scripts.seed_data

Requires GOOGLE_APPLICATION_CREDENTIALS or Firestore emulator to be running.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.models.company import CompanyCreate, ReportingContact
from app.models.fund import FundCreate, FundSettings
from app.models.metric_schema import DEFAULT_PE_METRICS, MetricDefinition
from app.services.firestore import firestore_service


async def seed():
    """Create test fund with 3 portfolio companies."""
    print("Seeding Firestore...")

    # ─── Fund ───
    fund = await firestore_service.create_fund(
        FundCreate(
            name="Meridian Capital Fund III",
            manager_name="Sarah Mitchell",
            manager_email="sarah.mitchell@meridian.example.com",
            settings=FundSettings(
                digest_frequency="weekly",
                staleness_amber_days=21,
                staleness_red_days=45,
            ),
        )
    )
    print(f"  Created fund: {fund.name} (ID: {fund.id})")

    # ─── Company A: Well-structured Excel reporter ───
    company_a = await firestore_service.create_company(
        CompanyCreate(
            fund_id=fund.id,
            name="NorthStar Logistics",
            sector="Logistics & Distribution",
            primary_contact_name="James Chen",
            primary_contact_email="james.chen@northstar.example.com",
            reporting_contacts=[
                ReportingContact(
                    name="Lisa Park", email="lisa.park@northstar.example.com", role="Financial Controller"
                ),
            ],
            canonical_metrics=DEFAULT_PE_METRICS,
            mapping_instructions=(
                "NorthStar uses Sage. Their management pack has tabs: 'P&L Summary', "
                "'Balance Sheet', 'Cash Flow'. Revenue is labelled 'Net Sales'. "
                "EBITDA is labelled 'Operating Profit Before D&A'."
            ),
            reporting_frequency="monthly",
            accounting_system="Sage",
        )
    )
    print(f"  Created company: {company_a.name} (ID: {company_a.id})")

    # ─── Company B: CSV export from Xero ───
    company_b = await firestore_service.create_company(
        CompanyCreate(
            fund_id=fund.id,
            name="BrightPath Education",
            sector="Education & Training",
            primary_contact_name="Priya Sharma",
            primary_contact_email="priya@brightpath.example.com",
            canonical_metrics=DEFAULT_PE_METRICS,
            mapping_instructions=(
                "BrightPath exports from Xero as CSV. Flat file format. "
                "Revenue is 'Total Income'. They don't separate EBITDA — "
                "calculate from 'Total Income' minus 'Total Expenses' plus 'Depreciation'."
            ),
            reporting_frequency="monthly",
            accounting_system="Xero",
        )
    )
    print(f"  Created company: {company_b.name} (ID: {company_b.id})")

    # ─── Company C: PDF board pack ───
    company_c = await firestore_service.create_company(
        CompanyCreate(
            fund_id=fund.id,
            name="Helix Manufacturing",
            sector="Manufacturing",
            primary_contact_name="Tom Richardson",
            primary_contact_email="tom@helix.example.com",
            canonical_metrics=DEFAULT_PE_METRICS + [
                MetricDefinition(
                    name="units_produced",
                    label="Units Produced",
                    type="number",
                    unit="units",
                    category="operational",
                    is_required=False,
                    variance_threshold=0.15,
                ),
            ],
            mapping_instructions=(
                "Helix sends a PDF board pack. Financial data is in tables on pages 3-5. "
                "Revenue is 'Turnover'. Cash balance is 'Bank & Cash'. "
                "They also report 'Units Produced' which maps to our operational KPI."
            ),
            reporting_frequency="quarterly",
            accounting_system="QuickBooks",
        )
    )
    print(f"  Created company: {company_c.name} (ID: {company_c.id})")

    print(f"\nDone! Fund ID: {fund.id}")
    print(f"Use this fund_id for the dashboard: /static/dashboard.html?fund_id={fund.id}")


if __name__ == "__main__":
    asyncio.run(seed())
