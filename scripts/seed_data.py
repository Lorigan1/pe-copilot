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
                # ─── P&L ───
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
                # ─── Balance Sheet ───
                LabelMapping(label="Property, Plant & Equipment", metric_name="ppe"),
                LabelMapping(label="Intangible Assets", metric_name="intangible_assets"),
                LabelMapping(label="Total Fixed Assets", metric_name="total_fixed_assets"),
                LabelMapping(label="Stock", metric_name="stock"),
                LabelMapping(label="Trade Debtors", metric_name="trade_debtors"),
                LabelMapping(label="Other Debtors", metric_name="other_debtors"),
                LabelMapping(label="Bank & Cash", metric_name="bank_cash"),
                LabelMapping(label="Total Current Assets", metric_name="total_current_assets"),
                LabelMapping(label="Trade Creditors", metric_name="trade_creditors"),
                LabelMapping(label="Other Creditors", metric_name="other_creditors"),
                LabelMapping(label="Tax Payable", metric_name="tax_payable"),
                LabelMapping(label="Total Current Liabilities", metric_name="total_current_liabilities"),
                LabelMapping(label="Net Current Assets", metric_name="net_current_assets"),
                LabelMapping(label="NET ASSETS", metric_name="net_assets"),
                LabelMapping(label="Share Capital", metric_name="share_capital"),
                # ─── Cash Flow ───
                LabelMapping(label="Depreciation & Amortisation", metric_name="dep_amort_cf"),
                LabelMapping(label="(Increase)/Decrease in Debtors", metric_name="debtors_change"),
                LabelMapping(label="(Increase)/Decrease in Stock", metric_name="stock_change"),
                LabelMapping(label="Increase/(Decrease) in Creditors", metric_name="creditors_change"),
                LabelMapping(label="Cash from Operations", metric_name="cash_from_operations"),
                LabelMapping(label="Tax Paid", metric_name="tax_paid"),
                LabelMapping(label="Net Cash from Operating", metric_name="net_cash_operating"),
                LabelMapping(label="Purchase of Fixed Assets", metric_name="purchase_fa"),
                LabelMapping(label="Sale of Fixed Assets", metric_name="sale_fa"),
                LabelMapping(label="Net Cash from Investing", metric_name="net_cash_investing"),
                LabelMapping(label="Bank Loan Drawdown", metric_name="loan_drawdown"),
                LabelMapping(label="Loan Repayments", metric_name="loan_repayments"),
                LabelMapping(label="Net Cash from Financing", metric_name="net_cash_financing"),
                LabelMapping(label="Net Change in Cash", metric_name="net_change_cash"),
                LabelMapping(label="Opening Cash Balance", metric_name="opening_cash"),
                LabelMapping(label="Closing Cash Balance", metric_name="closing_cash"),
            ],
            calculation_rules=[
                # ─── P&L rules ───
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
                # ─── Balance Sheet rules ───
                CalculationRule(
                    metric_name="total_fixed_assets",
                    source_label="Total Fixed Assets",
                    formula="ppe + intangible_assets",
                    description="PPE plus Intangibles",
                ),
                CalculationRule(
                    metric_name="total_current_assets",
                    source_label="Total Current Assets",
                    formula="stock + trade_debtors + other_debtors + bank_cash",
                    description="Sum of all current asset line items",
                ),
                CalculationRule(
                    metric_name="total_current_liabilities",
                    source_label="Total Current Liabilities",
                    formula="trade_creditors + other_creditors + tax_payable",
                    description="Sum of all current liability line items (stored as negative)",
                ),
                CalculationRule(
                    metric_name="net_current_assets",
                    source_label="Net Current Assets",
                    formula="total_current_assets + total_current_liabilities",
                    description="Current Assets plus Current Liabilities (liabilities are negative)",
                ),
                CalculationRule(
                    metric_name="net_assets",
                    source_label="NET ASSETS",
                    formula="total_fixed_assets + net_current_assets",
                    description="Fixed Assets plus Net Current Assets",
                ),
                # ─── Cash Flow rules ───
                CalculationRule(
                    metric_name="cash_from_operations",
                    source_label="Cash from Operations",
                    formula="operating_profit + dep_amort_cf + debtors_change + stock_change + creditors_change",
                    description="Operating profit plus working capital movements",
                ),
                CalculationRule(
                    metric_name="net_cash_operating",
                    source_label="Net Cash from Operating",
                    formula="cash_from_operations + tax_paid",
                    description="Cash from operations minus tax",
                ),
                CalculationRule(
                    metric_name="net_cash_investing",
                    source_label="Net Cash from Investing",
                    formula="purchase_fa + sale_fa",
                    description="Capital expenditure net of disposals",
                ),
                CalculationRule(
                    metric_name="net_cash_financing",
                    source_label="Net Cash from Financing",
                    formula="loan_drawdown + loan_repayments",
                    description="Net borrowing activity",
                ),
                CalculationRule(
                    metric_name="net_change_cash",
                    source_label="Net Change in Cash",
                    formula="net_cash_operating + net_cash_investing + net_cash_financing",
                    description="Total cash movement for the period",
                ),
                CalculationRule(
                    metric_name="closing_cash",
                    source_label="Closing Cash Balance",
                    formula="opening_cash + net_change_cash",
                    description="Opening balance plus net cash change",
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
