# PE CoPilot — Session Work: Calculation Rules, Upload Form & GCP Integration

What was built across these sessions, how to reproduce it, and how to use it.

---

## Summary of changes

| Task | Status | Files changed |
|------|--------|---------------|
| NorthStar cash flow fix | Complete | `testdata/NorthStar_Logistics_Jan2026.xlsx`, `testdata/NorthStar_Logistics_Feb2026.xlsx` |
| BrightPath calculation rules | Complete | `scripts/seed_data.py`, `testdata/BrightPath_Education_Jan2026.csv`, `tests/test_calculator.py`, `tests/test_csv_normalisation.py` |
| Helix calculation rules | Complete | `scripts/seed_data.py`, `testdata/Helix_Manufacturing_Q4_2025.pdf`, `tests/test_calculator.py`, `tests/test_pdf_normalisation.py` |
| Upload form | Complete | `app/static/upload.html`, `app/routers/process.py` |
| GCP integration (Pub/Sub, retries, staleness) | Complete | See `docs/GCP_INTEGRATION.md` |

---

## 1. NorthStar cash flow fix

### Problem

The cash flow sheet in the NorthStar Excel test data had hardcoded "Operating Profit" values that didn't match the P&L calculation chain:

| Period | Cash Flow had | P&L calculation gives |
|--------|---------------|----------------------|
| Jan 2026 | 85,125 | 374,850 |
| Feb 2026 | 79,825 | 397,160 |

This caused variance artifacts when the Layer 1.5 calculator computed correct values but the raw data showed different numbers.

### Fix

Regenerated both Excel test data files with corrected Operating Profit values on the Cash Flow sheet, matching the P&L chain: Revenue → Gross Profit → EBITDA → Operating Profit.

### Reproduce

```bash
# The corrected test data files are already in the repo
ls testdata/NorthStar_Logistics_Jan2026.xlsx
ls testdata/NorthStar_Logistics_Feb2026.xlsx

# Verify the calculation chain in tests
python -m pytest tests/test_calculator.py -k "NorthStar" -v
```

### Verify

The NorthStar calculator tests validate the full chain for both periods:

- Revenue → Cost of Sales → **Gross Profit** (add, because Sage stores costs as negative)
- Gross Profit → Total Overheads → **EBITDA**
- EBITDA → D&A → **Operating Profit**
- Operating Profit → Interest → **PBT**

---

## 2. BrightPath Education calculation rules (CSV/Xero)

### What was built

BrightPath exports from Xero as flat CSV files. Unlike NorthStar (Sage), Xero stores costs as **positive** values. The calculation rules use subtraction instead of addition.

### Label mappings (11)

Added to `scripts/seed_data.py` and seeded into Firestore:

| Raw label | Maps to |
|-----------|---------|
| Total Income | revenue |
| Total Cost of Sales | cost_of_sales |
| Gross Profit | gross_profit (blank — computed) |
| Total Expenses | total_expenses |
| Depreciation | depreciation |
| Net Profit | net_income (blank — computed) |
| EBITDA | ebitda (blank — computed) |
| Cash and Bank Accounts | cash_balance |
| Total Debt Outstanding | total_debt |
| Net Assets | net_assets |
| Headcount | headcount |

### Calculation rules (3)

```
gross_profit = revenue - cost_of_sales
ebitda = revenue - cost_of_sales - total_expenses + depreciation
net_income = revenue - cost_of_sales - total_expenses
```

Key difference from NorthStar: **subtract** costs (positive values) instead of adding them (negative values).

### Test data

`testdata/BrightPath_Education_Jan2026.csv` was modified to have blank Gross Profit, Net Profit, and EBITDA cells so the calculator fills them with `[COMPUTED]` markers.

### Reproduce

```bash
# Seed BrightPath rules into Firestore
python -m scripts.seed_data

# Run BrightPath-specific tests
python -m pytest tests/test_calculator.py -k "BrightPath" -v
python -m pytest tests/test_csv_normalisation.py -v
```

### Verify

Expected computed values (Jan 2026):

| Metric | Formula | Value |
|--------|---------|-------|
| Gross Profit | 875,000 - 437,500 | 437,500 |
| EBITDA | 875,000 - 437,500 - 306,250 + 17,500 | 148,750 |
| Net Income | 875,000 - 437,500 - 306,250 | 131,250 |

EBITDA margin of ~17% is typical for an education company.

---

## 3. Helix Manufacturing calculation rules (PDF/QuickBooks)

### What was built

Helix sends a quarterly board pack as PDF. The PDF parser (pdfplumber) extracts tables from pages 3-5. Costs are positive (like BrightPath).

### Label mappings (14)

| Raw label | Maps to |
|-----------|---------|
| Turnover | revenue |
| Cost of Goods Sold | cogs |
| Gross Profit | gross_profit (blank — computed) |
| Operating Expenses | operating_expenses |
| EBITDA | ebitda (blank — computed) |
| Depreciation & Amortisation | dep_amort |
| Net Income | net_income (blank — computed) |
| Bank & Cash | cash_balance |
| Term Loan | term_loan |
| Overdraft Facility | overdraft |
| Total Debt | total_debt (blank — computed) |
| Net Assets | net_assets |
| Units Produced | units_produced |
| Headcount | headcount |

### Calculation rules (4)

```
gross_profit = revenue - cogs
ebitda = gross_profit - operating_expenses
net_income = ebitda - dep_amort
total_debt = term_loan + overdraft
```

### Test data

`testdata/Helix_Manufacturing_Q4_2025.pdf` was regenerated with blank formula cells for Gross Profit, EBITDA, Net Income, and Total Debt.

### Reproduce

```bash
# Seed Helix rules into Firestore
python -m scripts.seed_data

# Run Helix-specific tests
python -m pytest tests/test_calculator.py -k "Helix" -v
python -m pytest tests/test_pdf_normalisation.py -v
```

### Verify

Expected computed values (Q4 2025):

| Metric | Formula | Value |
|--------|---------|-------|
| Gross Profit | 3,500,000 - 2,100,000 | 1,400,000 |
| EBITDA | 1,400,000 - 735,000 | 665,000 |
| Net Income | 665,000 - 112,000 | 553,000 |
| Total Debt | 1,200,000 + 150,000 | 1,350,000 |

EBITDA margin of ~19% is typical for a manufacturing company.

---

## 4. Upload form

### What was built

Interactive file upload form at `/static/upload.html` that auto-processes files after upload.

### Features

- Dark blue header matching the dashboard styling
- Company dropdown populated from `/api/v1/companies?fund_id=X`
- Period text input (e.g. "Jan 2026", "Q4 2025")
- Drag-and-drop file picker (accepts .xlsx, .xls, .csv, .pdf)
- Progress bar with step indicators (uploading → processing → normalising)
- Status polling every 3 seconds via `GET /api/v1/process/{update_id}/status`
- Success/failure display with confidence percentage
- Link to dashboard on completion

### Usage

Open in browser:

```
https://YOUR_CLOUD_RUN_URL/static/upload.html?api_key=YOUR_API_KEY
```

Or locally:

```
http://localhost:8080/static/upload.html?api_key=your-local-dev-key
```

The `fund_id` parameter is optional — defaults are configured in the form. The `api_key` parameter is used for API authentication.

### New endpoint

`GET /api/v1/process/{update_id}/status` was added to `app/routers/process.py` to support polling. Returns the full Update object including `processing_status`.

---

## 5. Layer 1.5 calculator — how it works

The calculator (`app/services/calculator.py`) is the deterministic computation layer that runs **between** text extraction and LLM normalisation.

### Why it exists

Without it, Claude would need to compute derived metrics (gross profit, EBITDA, etc.) from raw line items. This caused two problems:

1. **Inconsistent calculations** — Claude might compute slightly differently across periods, creating phantom variances
2. **Lower confidence** — Claude was less certain when it had to both map labels AND calculate values

### How it works

```
Raw file → Layer 1 (extract text) → Layer 1.5 (calculate) → Layer 2 (Claude maps) → Layer 3 (validate)
```

1. **Parse**: Reads pipe-separated extracted text, maps raw labels to internal metric names using the company's `label_mappings`
2. **Calculate**: Evaluates each `calculation_rule` formula using a safe AST-based evaluator (whitelist: +, -, *, /)
3. **Inject**: Fills blank cells in the extracted text with computed values, marked as `[COMPUTED]`

Claude then sees the enriched text with `[COMPUTED]` markers and maps it to the canonical schema. Because the values are pre-calculated deterministically, they're consistent across periods.

### Accounting system conventions

| System | Costs stored as | Formula pattern |
|--------|----------------|-----------------|
| Sage (NorthStar) | Negative | `gross_profit = revenue + cost_of_sales` |
| Xero (BrightPath) | Positive | `gross_profit = revenue - cost_of_sales` |
| QuickBooks (Helix) | Positive | `gross_profit = revenue - cogs` |

The formula engine is agnostic — the sign convention is encoded in each company's rules.

---

## 6. Variance calculation

### How it works

When processing an update, the system:

1. Fetches the previous completed update for the same company (from Firestore, ordered by `received_at`)
2. Calculates percentage change for each metric: `(current - previous) / abs(previous)`
3. Stores variances in the update record
4. Passes variances to Claude for the summarisation step

### Thresholds

The default variance threshold is 20% (configurable per fund). Variances above this threshold are flagged in the executive summary.

### Test coverage

```bash
python -m pytest tests/test_variance.py -v
```

Tests cover: NorthStar Jan→Feb revenue variance (+6.5%), cash variance (-8%), and edge cases (no previous period, zero values).

---

## Full test suite

```bash
# Install dev dependencies
pip install ".[dev]"

# Run all 187 tests
python -m pytest tests/ -v
```

### Test breakdown

| Test file | Tests | What it covers |
|-----------|-------|----------------|
| test_calculator.py | 73 | Numeric parsing, text parsing, formula evaluation, NorthStar/BrightPath/Helix integration |
| test_csv_normalisation.py | 10 | BrightPath full pipeline (CSV → extract → calculate → normalise) |
| test_pdf_normalisation.py | 8 | Helix full pipeline (PDF → extract → calculate → normalise) |
| test_variance.py | 10 | Variance calculation, NorthStar Jan→Feb pipeline |
| test_storage.py | 16 | GCS exceptions, URL parsing, retry config |
| test_pubsub.py | 5 | Message format, publish, errors |
| test_ingest_transaction.py | 9 | Transaction safety, process-event endpoint |
| test_staleness.py | 11 | Staleness thresholds, check logic |
| Others | 45 | Excel/CSV parsing, health scoring, endpoints |

---

## Deployment checklist

After making changes, deploy with:

```bash
PROJECT_ID=$(gcloud config get-value project)
REGION=europe-west2
VERSION=vN  # increment
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/pe-copilot/pe-copilot-api:${VERSION}"

gcloud auth configure-docker ${REGION}-docker.pkg.dev
docker build --platform linux/amd64 --no-cache -t $IMAGE .
docker push $IMAGE

gcloud run deploy pe-copilot-api \
  --image $IMAGE \
  --region $REGION \
  --platform managed \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 3 \
  --set-env-vars "GCP_PROJECT_ID=${PROJECT_ID},GCS_RAW_UPLOADS_BUCKET=${PROJECT_ID}-raw-uploads,GCS_REPORTS_BUCKET=${PROJECT_ID}-reports,API_KEY=your-production-key,ANTHROPIC_API_KEY=your-sk-ant-key"
```

After deploy:

1. Seed the calculation rules: `python -m scripts.seed_data`
2. Upload test files for all 3 companies via the upload form
3. Verify the dashboard shows correct metrics
4. Check logs: `gcloud run services logs read pe-copilot-api --region=europe-west2 --limit=30`
