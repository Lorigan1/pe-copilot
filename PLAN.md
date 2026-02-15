# Implementation Plan: Cash Fix, Calculation Rules Extension, Upload Form

## Phase 1: Fix NorthStar Cash Flow Discrepancy

The cash flow sheet has hardcoded "Operating Profit" values that don't match the P&L calculation chain.

**Current (wrong):**
- Jan CF "Operating Profit": 85,125 → should be 374,850
- Feb CF "Operating Profit": 79,825 → should be 397,160

**Also fix "Depreciation & Amortisation":**
- Jan CF: 73,500 → should match P&L (61,250 + 12,250 = 73,500) ✓ already correct
- Feb CF: 78,300 → should match P&L (65,250 + 13,050 = 78,300) ✓ already correct

**Files to change:**
- Regenerate `testdata/NorthStar_Logistics_Jan2026.xlsx` with corrected CF Operating Profit
- Regenerate `testdata/NorthStar_Logistics_Feb2026.xlsx` with corrected CF Operating Profit

## Phase 2: BrightPath Education Calculation Rules (CSV/Xero)

**Data format:** Flat CSV, single period column, all values pre-computed as positive numbers.

**Key difference from NorthStar:** Xero exports costs as positive values (e.g., "Total Cost of Sales: 437500" not "-437500"). The calculation layer needs to handle this via formula design — we subtract instead of add.

**Label mappings (13):**
- Total Income → revenue
- Course Fees, Corporate Training Contracts, Government Grants, Other Income (sub-items)
- Total Cost of Sales → cost_of_sales
- Gross Profit → gross_profit
- Total Expenses → total_expenses
- Depreciation → depreciation
- Net Profit → net_income
- Cash and Bank Accounts → cash_balance
- Total Debt Outstanding → total_debt
- Net Assets → net_assets
- Headcount → headcount

**Calculation rules (3):**
- `gross_profit = revenue - cost_of_sales` (subtract because Xero stores costs as positive)
- `ebitda = revenue - cost_of_sales - total_expenses + depreciation` (add back depreciation)
- `net_income = revenue - cost_of_sales - total_expenses` (bottom line check)

**Test data change:** Make Gross Profit and Net Profit blank in CSV so the calculator fills them. Currently all values are pre-computed — we need blank formula rows for the calculation layer to add value.

**Files to change:**
- `testdata/BrightPath_Education_Jan2026.csv` — blank out Gross Profit, Net Profit, optionally EBITDA row
- `scripts/seed_data.py` — add BrightPath label_mappings and calculation_rules
- `tests/test_csv_normalisation.py` — update if needed for [COMPUTED] markers
- Add BrightPath-specific calculator tests

## Phase 3: Helix Manufacturing Calculation Rules (PDF/QuickBooks)

**Data format:** 5-page PDF board pack. Tables on pages 3-5 extracted as pipe-separated rows with Q4 2025 | Q3 2025 column headers.

**Key structure from the PDF:**
- Page 3: P&L table (Turnover, Cost of Goods Sold, Gross Profit, Operating Expenses, EBITDA, D&A, Net Income)
- Page 4: Balance Sheet (Bank & Cash, Term Loan, Overdraft Facility, Total Debt, Net Assets)
- Page 5: Operational KPIs (Units Produced, Capacity Utilisation, Headcount)

**Label mappings (~15):**
- Turnover → revenue
- Cost of Goods Sold → cogs
- Gross Profit → gross_profit
- Operating Expenses → operating_expenses
- EBITDA → ebitda
- Depreciation & Amortisation → dep_amort
- Net Income → net_income
- Bank & Cash → cash_balance
- Term Loan → term_loan
- Overdraft Facility → overdraft
- Total Debt → total_debt
- Net Assets → net_assets
- Headcount → headcount
- Units Produced → units_produced

**Calculation rules (4):**
- `gross_profit = revenue - cogs`
- `ebitda = gross_profit - operating_expenses`
- `net_income = ebitda - dep_amort`
- `total_debt = term_loan + overdraft`

**Test data change:** Regenerate the PDF with blank formula rows for Gross Profit, EBITDA, Net Income, Total Debt so the calculator fills them deterministically.

**Files to change:**
- Regenerate `testdata/Helix_Manufacturing_Q4_2025.pdf` with blank formula cells
- `scripts/seed_data.py` — add Helix label_mappings and calculation_rules
- `tests/test_pdf_normalisation.py` — update for [COMPUTED] markers
- Add Helix-specific calculator tests

## Phase 4: Calculator Enhancement for Positive-Cost Convention

BrightPath (Xero) stores costs as positive numbers. Currently `calculator.py` formulas use addition (because NorthStar stores costs as negative). We need subtraction formulas for BrightPath.

**No code changes needed** — the formula engine already supports subtraction (`revenue - cost_of_sales`). The difference is purely in how we write the formulas in each company's `calculation_rules`.

## Phase 5: Upload Form

**Current state:** Dashboard has an "Upload" link in the header but it likely points to a non-existent page or placeholder.

**Plan:** Create `app/static/upload.html` (or enhance dashboard.html with a modal) that:
1. Matches dashboard styling (dark blue header, card-based layout)
2. Has a company dropdown (fetched from `/api/v1/companies?fund_id=X`)
3. Period input (month picker or text field like "2026-02")
4. File picker (accepts .xlsx, .xls, .csv, .pdf)
5. Upload button → POST to `/api/v1/ingest/upload`
6. Auto-triggers processing → POST to `/api/v1/process/{update_id}`
7. Shows progress/status and redirects to dashboard on completion

**Files to change:**
- `app/static/upload.html` (new or enhanced)
- Possibly update dashboard.html header link

## Phase 6: Run Full Test Suite and Deploy

- Run all tests (existing 125 + new BrightPath/Helix calculator tests)
- Commit and push
- Deploy to Cloud Run
- Update BrightPath and Helix company records in Firestore with new rules
- Re-upload and process all test data for all three companies
- Verify dashboard shows clean data across all companies

## Test Strategy

For each company, verify:
1. **Deterministic calculation is correct** — unit tests with known inputs
2. **[COMPUTED] markers injected** — enriched text contains markers
3. **LLM uses computed values** — integration tests confirm Claude doesn't recalculate
4. **Variances are consistent** — same formula applied across periods
5. **Graceful degradation** — if a label is missing, calculation skips gracefully
