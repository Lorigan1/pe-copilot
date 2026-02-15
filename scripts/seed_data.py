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

from app.models.calculation_rule import CalculationRule, LabelMapping
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
            label_mappings=[
                LabelMapping(label="Net Sales", metric_name="net_sales"),
                LabelMapping(label="Cost of Sales", metric_name="cost_of_sales"),
                LabelMapping(label="Gross Profit", metric_name="gross_profit"),
                LabelMapping(label="Warehouse & Distribution", metric_name="warehouse_distribution"),
                LabelMapping(label="Fleet Operating Costs", metric_name="fleet_costs"),
                LabelMapping(label="Staff Costs", metric_name="staff_costs"),
                LabelMapping(label="Premises", metric_name="premises"),
                LabelMapping(label="Professional Fees", metric_name="professional_fees"),
                LabelMapping(label="Other Overheads", metric_name="other_overheads"),
                LabelMapping(label="Total Overheads", metric_name="total_overheads"),
                LabelMapping(label="Operating Profit Before D&A", metric_name="ebitda"),
                LabelMapping(label="Depreciation", metric_name="depreciation"),
                LabelMapping(label="Amortisation", metric_name="amortisation"),
                LabelMapping(label="Operating Profit", metric_name="operating_profit"),
                LabelMapping(label="Interest Payable", metric_name="interest_payable"),
                LabelMapping(label="Profit Before Tax", metric_name="pbt"),
                LabelMapping(label="Net Profit", metric_name="net_income"),
            ],
            calculation_rules=[
                CalculationRule(
                    metric_name="gross_profit",
                    source_label="Gross Profit",
                    formula="net_sales + cost_of_sales",
                    description="Revenue minus Cost of Sales (costs stored as negative)",
                ),
                CalculationRule(
                    metric_name="total_overheads",
                    source_label="Total Overheads",
                    formula="warehouse_distribution + fleet_costs + staff_costs + premises + professional_fees + other_overheads",
                    description="Sum of all overhead line items (all stored as negative)",
                ),
                CalculationRule(
                    metric_name="ebitda",
                    source_label="Operating Profit Before D&A",
                    formula="gross_profit + total_overheads",
                    description="Gross Profit plus Total Overheads (overheads are negative)",
                ),
                CalculationRule(
                    metric_name="operating_profit",
                    source_label="Operating Profit",
                    formula="ebitda + depreciation + amortisation",
                    description="EBITDA plus D&A (D&A stored as negative)",
                ),
                CalculationRule(
                    metric_name="pbt",
                    source_label="Profit Before Tax",
                    formula="operating_profit + interest_payable",
                    description="Operating Profit plus Interest (interest stored as negative)",
                ),
            ],
            mapping_instructions=(
                "NorthStar uses Sage. Their management pack has tabs: 'P&L Summary', "
                "'Balance Sheet', 'Cash Flow'. Revenue is labelled 'Net Sales'. "
                "EBITDA is labelled 'Operating Profit Before D&A'. "
                "Values marked [COMPUTED] have been pre-calculated deterministically — "
                "use these values as-is, do not recalculate."
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
