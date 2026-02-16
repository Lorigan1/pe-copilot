# PE CoPilot

A GCP-native financial data normalisation engine for private equity fund managers. Ingests heterogeneous financial reports (Excel, CSV, PDF) from portfolio companies and produces unified, comparable metrics through a multi-layer processing pipeline.

## The problem

Portfolio companies report in different formats, with different labels, different accounting systems, and different conventions. One company calls it "Net Sales", another "Total Revenue", a third "Turnover". Some send Excel workbooks, some CSV exports, some PDF board packs. Costs might be negative or positive. Formula cells might be blank.

PE CoPilot automates the entire normalisation workflow: upload a file, extract the data, map it to a canonical metric schema using AI, validate the output with deterministic rules, and display everything on a portfolio dashboard.

## Architecture

```
Upload -> Cloud Storage -> Firestore -> Pub/Sub -> Cloud Run -> Process
```

### Processing pipeline

| Layer | Name | What it does |
|-------|------|-------------|
| 1 | Extraction | Opens raw files and extracts text (openpyxl, pandas, pdfplumber) |
| 1.5 | Calculation | Applies company-specific formulas to fill gaps (gross profit, EBITDA, etc.) |
| 2 | AI Normalisation | Claude Sonnet maps raw labels to canonical metrics |
| 3 | Validation | Checks missing metrics, calculates period-over-period variances |
| 3.5 | Sanity Checks | Deterministic financial rules: sign constraints, accounting identities, magnitude bounds |
| Summary | AI Summary | Claude Haiku writes executive summary, risks, and action items |

### Model tiering

Sonnet handles financial data extraction (high stakes, messy input). Haiku handles summarisation (structured input, prose output). This cuts ~40-50% off token cost without sacrificing extraction accuracy.

### Content deduplication

Files are SHA-256 hashed at upload time. Duplicate content is rejected with 409 Conflict regardless of filename.

## Tech stack

- **Language:** Python 3.12
- **Framework:** FastAPI + Pydantic
- **Database:** Google Cloud Firestore
- **Storage:** Google Cloud Storage
- **Compute:** Google Cloud Run (containerised)
- **Messaging:** Google Cloud Pub/Sub (event-driven processing)
- **Scheduling:** Google Cloud Scheduler (staleness checks)
- **AI:** Anthropic Claude (Sonnet for extraction, Haiku for summarisation)
- **Deployment:** Docker, gcloud CLI

## Project structure

```
app/
  main.py                  # FastAPI app, 7 routers + internal router
  config.py                # Pydantic settings from env vars
  services/
    normaliser.py          # Core pipeline orchestration
    calculator.py          # Layer 1.5 formula engine
    validators.py          # Layer 3.5 financial sanity checks
    llm.py                 # Claude API wrapper (cache, retry, model routing)
    firestore.py           # Firestore CRUD
    storage.py             # GCS with retries and custom exceptions
    pubsub.py              # Pub/Sub publisher
    excel_parser.py        # Excel/CSV extraction
    pdf_parser.py          # PDF table extraction
  routers/
    ingest.py              # File upload (dedup + 3-step transactional)
    process.py             # Processing trigger + status polling
    companies.py           # Company CRUD + detail view
    dashboard.py           # Portfolio aggregation
    tasks.py               # Task CRUD + internal endpoints
    digest.py              # Digest generation (planned)
    export.py              # Report export (planned)
  models/                  # Pydantic models for all entities
  static/                  # Dashboard, upload form, company detail page
scripts/
  seed_data.py             # Seed funds, companies, and config into Firestore
  clear_updates.py         # Clear all updates for fresh testing
tests/                     # 224 automated tests
docs/                      # Setup, usage, GCP integration, system guide
testdata/                  # Sample financial reports for each company
```

## Quick start

### Prerequisites

- Python 3.12+
- Google Cloud project with Firestore, Cloud Storage, Pub/Sub enabled
- Anthropic API key
- Docker (for deployment)

### Local development

```bash
# Clone and install
git clone https://github.com/Lorigan1/pe-copilot.git
cd pe-copilot
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your GCP project ID, Anthropic API key, etc.

# Seed test data
python -m scripts.seed_data

# Run locally
uvicorn app.main:app --reload
```

### Run tests

```bash
python -m pytest tests/ -v
```

Tests run in under 2 seconds with no cloud credentials required (all external services are mocked).

### Deploy to Cloud Run

```bash
gcloud run deploy pe-copilot-api \
  --source . \
  --region europe-west2 \
  --allow-unauthenticated
```

See `docs/SETUP.md` for full infrastructure setup and `docs/GCP_INTEGRATION.md` for Pub/Sub, Scheduler, and storage configuration.

## API

All endpoints require an `X-API-Key` header. Full interactive docs available at `/docs` (Swagger UI).

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/ingest/upload` | Upload a financial report |
| GET | `/api/v1/process/{id}/status` | Check processing status |
| GET | `/api/v1/dashboard/portfolio?fund_id=X` | Portfolio overview |
| GET | `/api/v1/companies/{id}/detail?fund_id=X` | Company detail view |
| GET | `/api/v1/companies?fund_id=X` | List companies |
| GET | `/api/v1/tasks?fund_id=X` | List tasks |

### Web UI

| Page | URL |
|------|-----|
| Dashboard | `/static/dashboard.html?fund_id=X&api_key=Y` |
| Upload | `/static/upload.html?api_key=Y` |
| Company detail | `/static/company-detail.html?company_id=X&fund_id=Y` |

## Canonical metrics

Every company's data is normalised to nine standard metrics:

| Metric | Type | Description |
|--------|------|-------------|
| `revenue` | Currency (GBP) | Total revenue / net sales / turnover |
| `gross_profit` | Currency (GBP) | Revenue minus cost of sales |
| `ebitda` | Currency (GBP) | Earnings before interest, tax, depreciation, amortisation |
| `net_income` | Currency (GBP) | Bottom-line profit after tax |
| `cash_balance` | Currency (GBP) | Bank and cash at period end |
| `total_debt` | Currency (GBP) | All borrowings and debt obligations |
| `net_assets` | Currency (GBP) | Total assets minus total liabilities |
| `operating_cashflow` | Currency (GBP) | Cash generated from operations |
| `headcount` | Number (FTE) | Full-time equivalent employees |

Each company has `mapping_instructions` that tell Claude how their specific labels map to these canonical names.

## Portfolio companies (test data)

| Company | Accounting System | File Format | Calculation Rules |
|---------|-------------------|-------------|-------------------|
| NorthStar Logistics | Sage | Excel (.xlsx) | 5 rules (gross profit, overheads, EBITDA, operating profit, PBT) |
| BrightPath Education | Xero | CSV (.csv) | 3 rules (gross profit, EBITDA, net income) |
| Helix Manufacturing | QuickBooks | PDF (.pdf) | 4 rules (gross profit, EBITDA, net income, total debt) |

## Documentation

| Document | Contents |
|----------|----------|
| `docs/SETUP.md` | Full setup from scratch (GCP project, Firestore, GCS, IAM) |
| `docs/USAGE.md` | Day-to-day usage, API reference, operations guide |
| `docs/GCP_INTEGRATION.md` | Pub/Sub, Cloud Scheduler, storage hardening, transaction safety |
| `docs/SESSION_WORK.md` | Detailed record of calculation rules and all session changes |
| `docs/CONTINUATION_BRIEF.md` | Context brief for resuming development in a new session |
| `docs/PE_CoPilot_System_Guide.docx` | Non-technical guide to the architecture and what's been built |

## Roadmap

- **Email ingestion** - Accept reports via email (SendGrid inbound parse)
- **Digest reports** - Weekly/monthly email summaries across the portfolio
- **Google Sheets export** - Push normalised data to a shared Sheet
- **PDF report generation** - Formatted reports for board meetings
- **OCR support** - Handle scanned PDFs (Google Document AI)
- **Multi-currency** - Support companies reporting in different currencies

## License

Private repository. All rights reserved.
