# PE CoPilot — Usage & Operations Guide

How to use the system day-to-day: uploading files, processing them, viewing the dashboard, and managing data.

---

## Quick start

Your live app is at: `https://pe-copilot-api-917934808232.europe-west2.run.app`

| URL | What it does |
|---|---|
| `/health` | Health check — confirms the API is running |
| `/docs` | Swagger UI — interactive API documentation |
| `/static/dashboard.html?fund_id=FUND_ID&api_key=API_KEY` | Portfolio dashboard |
| `/static/upload.html?api_key=API_KEY` | File upload form |
| `/static/company-detail.html?company_id=X&fund_id=Y` | Company detail view (also accessible by clicking a dashboard card) |

**Current fund ID:** `OprI9mdcmQ9ZplIbzS0n` (Meridian Capital Fund III)

---

## The workflow

The typical flow for processing a portfolio company's financial report:

```
Upload file → Extract text → Normalise with Claude → Store in Firestore → View on dashboard
     ↓              ↓                  ↓                      ↓
  /ingest/upload   Automatic      /process/{id}         /dashboard/portfolio
```

### Step 1: Upload a file

**Via curl:**

```bash
curl -X POST \
  -H "X-API-Key: YOUR_API_KEY" \
  -F "file=@/path/to/report.xlsx" \
  -F "fund_id=OprI9mdcmQ9ZplIbzS0n" \
  -F "company_id=COMPANY_ID" \
  -F "source_file_type=excel" \
  -F "metrics_period=Jan 2026" \
  "https://pe-copilot-api-917934808232.europe-west2.run.app/api/v1/ingest/upload"
```

**Via the upload form:**

Open `/static/upload.html?api_key=YOUR_API_KEY` in your browser, select the company, drag and drop the file.

**Parameters:**

| Parameter | Required | Values |
|---|---|---|
| `file` | Yes | The file to upload (.xlsx, .csv, .pdf) |
| `fund_id` | Yes | The fund this company belongs to |
| `company_id` | Yes | The portfolio company ID |
| `source_file_type` | Yes | `excel`, `csv`, or `pdf` |
| `metrics_period` | No | E.g. "Jan 2026", "Q4 2025" |

**Response:** Returns an update object with `id` and `processing_status: "pending"`.

### Step 2: Processing (automatic)

Processing now triggers **automatically** via Pub/Sub after upload. You no longer need a separate API call.

**What happens behind the scenes:**
1. Upload publishes a message to the `file-ingestion-events` Pub/Sub topic
2. The push subscription calls `POST /api/v1/internal/process-event`
3. **Layer 1 (Extraction):** Downloads the file from Cloud Storage and extracts text/tables using the appropriate parser (openpyxl for Excel, pandas for CSV, pdfplumber for PDF)
4. **Layer 1.5 (Calculation):** Applies deterministic calculation rules — fills formula cells (gross profit, EBITDA, etc.) with `[COMPUTED]` markers
5. **Layer 2 (Normalisation):** Sends the enriched text to Claude along with the company's mapping instructions. Claude returns normalised metrics mapped to the canonical schema.
6. **Layer 3 (Validation):** Pydantic validates the response. Variances are calculated against the previous period. A summarisation call produces executive summary, risks, and action items.

**Status determination:**
- **completed**: confidence >= 0.5 AND missing metrics <= 2
- **needs_review**: low confidence or too many missing metrics
- **failed**: exception during processing

**Manual reprocessing** (if Pub/Sub failed or you want to re-run):

```bash
curl -X POST \
  -H "X-API-Key: YOUR_API_KEY" \
  "https://pe-copilot-api-917934808232.europe-west2.run.app/api/v1/process/UPDATE_ID"
```

**Check status** (the upload form polls this automatically):

```bash
curl -H "X-API-Key: YOUR_API_KEY" \
  "https://pe-copilot-api-917934808232.europe-west2.run.app/api/v1/process/UPDATE_ID/status"
```

### Step 3: View the dashboard

Open in browser:
```
https://pe-copilot-api-917934808232.europe-west2.run.app/static/dashboard.html?fund_id=OprI9mdcmQ9ZplIbzS0n&api_key=YOUR_API_KEY
```

Or via the API:
```bash
curl -H "X-API-Key: YOUR_API_KEY" \
  "https://pe-copilot-api-917934808232.europe-west2.run.app/api/v1/dashboard/portfolio?fund_id=OprI9mdcmQ9ZplIbzS0n"
```

---

## API reference

All endpoints require the `X-API-Key` header. Full interactive docs at `/docs`.

### Funds

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/funds` | Create a fund |
| GET | `/api/v1/funds/{fund_id}` | Get a fund |
| PATCH | `/api/v1/funds/{fund_id}` | Update a fund |

### Companies

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/companies?fund_id=X` | List companies in a fund |
| POST | `/api/v1/companies` | Create a company |
| GET | `/api/v1/companies/{id}` | Get a company |
| PATCH | `/api/v1/companies/{id}` | Update a company |
| GET | `/api/v1/companies/{id}/detail?fund_id=X` | Full company detail view (profile, updates, tasks, metrics trends) |

### Ingestion

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/ingest/upload` | Upload a file (multipart form) |

### Processing

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/process/{update_id}/status` | Get current processing status (for polling) |
| POST | `/api/v1/process/{update_id}` | Trigger normalisation pipeline (manual) |
| POST | `/api/v1/process/{update_id}/review` | Mark a needs_review update as reviewed |

### Internal (no API key — for GCP service callbacks)

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/internal/process-event` | Pub/Sub push handler — auto-processes uploads |
| POST | `/api/v1/internal/staleness-check?fund_id=X` | Cloud Scheduler — creates tasks for stale companies |

### Dashboard

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/dashboard/portfolio?fund_id=X` | Full portfolio view |

### Tasks

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/tasks?fund_id=X` | List tasks (optional filters: company_id, status, assigned_to) |
| POST | `/api/v1/tasks` | Create a task |
| PATCH | `/api/v1/tasks/{id}` | Update a task |

---

## Company IDs (test data)

| Company | ID | Sector | Expected file type |
|---|---|---|---|
| NorthStar Logistics | `3kRa7txt35WweOzO6LL6` | Logistics & Distribution | Excel (.xlsx) |
| BrightPath Education | `L6UNvXfxNuCC7cKEJ2Ku` | Education & Training | CSV (.csv) |
| Helix Manufacturing | `IpO2rgie3TdoldUcQXE7` | Manufacturing | PDF (.pdf) |

---

## Canonical metrics schema

Every company's data is normalised to this schema:

| Metric | Type | Unit | Description |
|---|---|---|---|
| `revenue` | currency | GBP | Total revenue / net sales / turnover |
| `gross_profit` | currency | GBP | Revenue minus cost of sales |
| `ebitda` | currency | GBP | Earnings before interest, tax, depreciation, amortisation |
| `net_income` | currency | GBP | Bottom-line profit after tax |
| `cash_balance` | currency | GBP | Bank & cash at period end |
| `total_debt` | currency | GBP | All borrowings and debt obligations |
| `net_assets` | currency | GBP | Total assets minus total liabilities |
| `operating_cashflow` | currency | GBP | Cash generated from operations |
| `headcount` | number | FTE | Number of full-time equivalent employees |

Each company has `mapping_instructions` that tell Claude how their specific labels map to these canonical names. For example, NorthStar's revenue is labelled "Net Sales" and their EBITDA is "Operating Profit Before D&A".

---

## Processing statuses

| Status | Meaning |
|---|---|
| `pending` | File uploaded, not yet processed |
| `processing` | Currently running through the pipeline |
| `completed` | Successfully normalised |
| `needs_review` | Low confidence or too many missing metrics — human review needed |
| `failed` | Error during processing (check `processing_error` field) |

---

## Health scoring

Companies are scored green/amber/red based on:

| Condition | Score |
|---|---|
| Last update < 21 days ago, low variance, no missing metrics | Green |
| Last update 21-45 days ago, moderate variance, 1-2 missing metrics | Amber |
| Last update > 45 days ago, high variance, 3+ missing metrics | Red |
| No updates ever received | Amber |

Thresholds are configurable per fund via `FundSettings`.

---

## Operations

### Checking logs

```bash
gcloud run services logs read pe-copilot-api --region=europe-west2 --limit=20
```

### Reprocessing a failed update

If an update failed (e.g. due to a missing index), just re-trigger it:

```bash
curl -X POST -H "X-API-Key: YOUR_KEY" \
  "https://YOUR_URL/api/v1/process/UPDATE_ID"
```

### Reviewing a flagged update

When the LLM confidence is low, the update goes to `needs_review`. After checking the data:

```bash
curl -X POST -H "X-API-Key: YOUR_KEY" \
  "https://YOUR_URL/api/v1/process/UPDATE_ID/review?reviewer_email=you@example.com"
```

### Adding a new portfolio company

```bash
curl -X POST \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "fund_id": "OprI9mdcmQ9ZplIbzS0n",
    "name": "NewCo Ltd",
    "sector": "Technology",
    "primary_contact_name": "Jane Smith",
    "primary_contact_email": "jane@newco.com",
    "mapping_instructions": "Revenue is labelled Total Income. They use FreeAgent.",
    "reporting_frequency": "monthly",
    "accounting_system": "FreeAgent"
  }' \
  "https://YOUR_URL/api/v1/companies"
```

The `mapping_instructions` field is critical — it tells Claude how to interpret this company's specific reporting format.

---

## File format notes

### Excel (.xlsx)
- Extracts all sheets, all cells
- Formula cells appear empty (only hardcoded values are extracted) — Claude infers from context
- Multi-sheet workbooks with P&L, Balance Sheet, Cash Flow work well

### CSV (.csv)
- Parsed with pandas
- Handles multiple encodings (UTF-8, Latin-1, CP1252)
- Best for flat exports from accounting systems (Xero, FreeAgent)

### PDF (.pdf)
- Parsed with pdfplumber
- Tables are extracted first, then surrounding text
- Works well with board packs that have tabular financial data
- Scanned/image PDFs will not work (no OCR yet)
