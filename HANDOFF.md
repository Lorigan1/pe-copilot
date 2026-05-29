# PE CoPilot — Session Handoff Document
> Generated: 2026-05-15

## What Is This Project?

PE CoPilot is a GCP-native financial data normalisation engine for private equity fund managers. It ingests heterogeneous financial reports (Excel, CSV, PDF) from portfolio companies and produces unified, comparable metrics via a multi-layer AI pipeline.

**Repo**: `https://github.com/Lorigan1/pe-copilot.git` (currently private, considering making public)
**Owner**: Paul Lorigan (`paul.lorigan1@gmail.com`)

## Tech Stack

- **Backend**: Python 3.12+, FastAPI 0.115+, Pydantic 2.10+
- **Database**: Google Cloud Firestore (Native mode)
- **Storage**: Google Cloud Storage (GCS)
- **Messaging**: Google Cloud Pub/Sub
- **AI/LLM**: Anthropic Claude (Sonnet for extraction, Haiku for summarisation)
- **Email**: SendGrid (optional — gracefully degrades when not configured)
- **Frontend**: Static HTML/JS (upload form, portfolio dashboard, company detail)
- **Deployment**: Docker → Google Cloud Run (europe-west2)

## Implementation Plan — 8 Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | Foundation (FastAPI scaffold, config, Docker) | **Complete** |
| 2 | Data Layer (Firestore models, GCS storage) | **Complete** |
| 3 | Ingestion (Upload → GCS → Firestore → Pub/Sub, dedup, parsers) | **Complete** |
| 4 | LLM Normalisation (Layer 1.5 calculator, Layer 2 Claude mapping, Layer 3 validation, Layer 3.5 validators) | **Complete** |
| 5 | Dashboard & Company Detail (portfolio view, trends, tasks, file downloads) | **Complete** |
| 6 | Alerts & Health Scoring (health scorer, normaliser integration, email alerts) | **Complete** |
| 7 | Digest & Exports (weekly digest, Google Sheets export, PDF reports) | **Not started** (endpoints return 501) |
| 8 | Hardening (caching, rate limiting, retries, monitoring) | **Not started** |

The full plan is in `PE_CoPilot_Implementation_Plan_v2.docx` (user-uploaded, in repo root).

## Processing Pipeline

```
Upload → GCS Store → Firestore Record → Pub/Sub Publish
                                              ↓
Layer 1: Extraction (Excel/CSV/PDF → raw text)
Layer 1.5: Deterministic Calculator (derived metrics: gross_profit, EBITDA, etc.)
Layer 2: LLM Normalisation (Claude Sonnet maps raw labels → 9 canonical metrics)
Layer 3: Validation (missing metrics, period-over-period variance calculation)
Layer 3.5: Sanity Validators (sign constraints, accounting identities, magnitude bounds, variance spikes)
Summarisation: Claude Haiku generates summary, risks, action items
Health Scoring: staleness + variances + missing metrics → green/amber/red
Email Alert: if health status changed, notify fund manager via SendGrid
```

## Canonical 9-Metric Schema

revenue, gross_profit, ebitda, net_income, cash_balance, total_debt, net_assets, operating_cashflow, headcount

## Uncommitted Changes (MUST COMMIT)

All Phase 5 completion + Phase 6 integration work is done but **not committed to git**. Here's what needs committing:

### Modified files:
- **`app/main.py`** — Added `files` router import and registration
- **`app/models/dashboard.py`** — Added `raw_file_urls` field to `UpdateSummaryDetail`
- **`app/services/firestore.py`** — Added `raw_file_urls=u.raw_file_urls` to company detail view construction
- **`app/services/normaliser.py`** — Major change: wired in health_scorer + email_sender after processing; replaces old simple `last_update_at` update with full health scoring, company update, and email alert on status change
- **`app/static/company-detail.html`** — Added `downloadFile()` JS function and download links in timeline

### New files:
- **`app/routers/files.py`** — GET `/api/v1/files/download` endpoint (signed URL generation for GCS files)
- **`app/services/email_sender.py`** — Full SendGrid email service with graceful degradation, HTML templates for health alerts and staleness alerts
- **`tests/test_email_sender.py`** — 10 tests for email service
- **`tests/test_files_router.py`** — 5 tests for file download endpoint
- **`tests/test_health_integration.py`** — 3 tests for health scoring in normaliser pipeline
- **`TEST_CARD.md`** — Comprehensive test card for the testing-agent (22 test files, 242 tests, regression checklist)

### Files that should NOT be committed:
- `PE_CoPilot_System_Guide.docx` / `.pdf` — generated docs, not source
- `docs/.~lock.*` and `docs/lu4521j5ugn.tmp` — temp files
- `CLAUDE.md` — if it exists, check contents first

### Suggested commit command:
```bash
git add app/main.py app/models/dashboard.py app/services/firestore.py app/services/normaliser.py \
  app/static/company-detail.html app/routers/files.py app/services/email_sender.py \
  tests/test_email_sender.py tests/test_files_router.py tests/test_health_integration.py \
  TEST_CARD.md

git commit -m "Complete Phase 5 (file downloads) and Phase 6 (health scoring + email alerts)

- Add signed URL file download endpoint (GET /api/v1/files/download)
- Wire health_scorer into normaliser pipeline (score after every update)
- Add SendGrid email alerts on health status changes (graceful degradation)
- Add raw_file_urls to company detail timeline with download links
- Add TEST_CARD.md for testing-agent
- 18 new tests (242 total, all passing)"

git push origin main
```

## Test Suite — 242 Tests, All Passing

Run: `python -m pytest tests/ -v --tb=short` (2.3s, fully mocked, no credentials needed)

| File | Area | Key Coverage |
|------|------|-------------|
| `test_calculator.py` | Layer 1.5 formula engine | Calculation rules, label mappings, NorthStar/BrightPath sign conventions |
| `test_excel_parser.py` | Excel extraction | Multi-sheet, headers, formatting |
| `test_csv_parser.py` | CSV extraction | Flat files, encoding |
| `test_pdf_parser.py` | PDF extraction | Multi-page tables, Helix cross-page continuation |
| `test_csv_normalisation.py` | CSV end-to-end | Extract → normalise → validate |
| `test_pdf_normalisation.py` | PDF end-to-end | Extract → normalise → validate |
| `test_ingest_transaction.py` | Upload transactions | GCS → Firestore → Pub/Sub with rollback |
| `test_dedup.py` | Deduplication | SHA-256 hash, 409 on duplicate |
| `test_validators.py` | Layer 3.5 sanity checks | Sign, identity, magnitude, zero-revenue, spikes |
| `test_model_tiering.py` | LLM model routing | Sonnet for extraction, Haiku for summary |
| `test_variance.py` | Variance calculation | Period-over-period % change |
| `test_health_scorer.py` | Health scoring logic | Staleness, variance, missing metrics |
| `test_health_integration.py` | Health in normaliser | Scorer called, company updated, email triggered |
| `test_health.py` | Health endpoint | GET /health returns 200 |
| `test_email_sender.py` | Email service | SendGrid graceful degradation, templates |
| `test_files_router.py` | File download | Signed URLs, auth, errors |
| `test_company_detail.py` | Company detail API | Profile, timeline, trends, tasks |
| `test_staleness.py` | Staleness detection | Thresholds, task creation |
| `test_pubsub.py` | Pub/Sub integration | Message publish, event handling |
| `test_storage.py` | GCS storage service | Upload, download, signed URLs, retries |
| `conftest.py` | Shared fixtures | Client (`test-key`), API headers, env vars |

**Testing-agent**: Use `TEST_CARD.md` with the `/testing-agent:run-tests` skill to run tests without holding them in context.

## API Surface (24 endpoints)

| Method | Endpoint | Auth | Status |
|--------|----------|------|--------|
| GET | `/health` | No | Working |
| GET | `/` | No | Working |
| POST | `/api/v1/ingest/upload` | Yes | Working |
| POST | `/api/v1/ingest/email` | Yes | 501 (Phase 7) |
| GET | `/api/v1/process/{update_id}/status` | Yes | Working |
| POST | `/api/v1/process/{update_id}` | Yes | Working |
| POST | `/api/v1/process/{update_id}/review` | Yes | Working |
| GET | `/api/v1/companies` | Yes | Working |
| GET | `/api/v1/companies/{id}` | Yes | Working |
| POST | `/api/v1/companies` | Yes | Working |
| PUT | `/api/v1/companies/{id}` | Yes | Working |
| GET | `/api/v1/companies/{id}/detail` | Yes | Working |
| GET | `/api/v1/dashboard/portfolio` | Yes | Working |
| GET | `/api/v1/tasks` | Yes | Working |
| POST | `/api/v1/tasks` | Yes | Working |
| PUT | `/api/v1/tasks/{id}` | Yes | Working |
| GET | `/api/v1/files/download` | Yes | Working |
| POST | `/api/v1/internal/process-event` | No (IAM) | Working |
| POST | `/api/v1/internal/staleness-check` | No (IAM) | Working |
| POST | `/api/v1/digest/generate` | Yes | 501 |
| GET | `/api/v1/digest/latest` | Yes | 501 |
| POST | `/api/v1/export/sheets/{company_id}` | Yes | 501 |
| POST | `/api/v1/export/pdf/{digest_id}` | Yes | 501 |

Auth = `X-API-Key` header. Dev key: `test-key` (set in `conftest.py`). Prod key: `API_KEY` env var.

## Known Regression Areas

These have broken before — watch closely when changing nearby code:

1. **NorthStar cash flow sign convention** — Sage stores costs as negative. Calculator subtracts (not adds) negative values.
2. **Ingest transaction mocks** — New async methods on `firestore_service` must be mocked as `AsyncMock(return_value=None)` in ingest tests.
3. **BrightPath positive cost convention** — Xero stores costs as positive. Uses `subtract` rules. Mixing conventions doubles costs.
4. **Helix PDF multi-table parsing** — Tables span pages 3-5, parser handles cross-page continuation.
5. **Duplicate file detection** — Content-based (SHA-256), not filename-based.
6. **Layer 3.5 vs processing status** — `NEEDS_REVIEW` from validators must not be overridden by normaliser's confidence check.

## Project Structure

```
pe-copilot/
├── app/
│   ├── config.py              # Settings from env vars
│   ├── dependencies.py        # FastAPI auth dependency (verify_api_key)
│   ├── main.py                # FastAPI app, router registration
│   ├── models/
│   │   ├── calculation_rule.py  # Layer 1.5 rule definitions
│   │   ├── company.py           # Company model (health_status, health_reasons)
│   │   ├── dashboard.py         # Portfolio + CompanyDetail view models
│   │   ├── fund.py              # Fund model (manager_email)
│   │   ├── llm_responses.py     # Pydantic models for Claude responses
│   │   ├── metric_schema.py     # DEFAULT_PE_METRICS (9 canonical metrics)
│   │   ├── task.py              # Task model for action items
│   │   └── update.py            # Update model (ProcessingStatus, SourceType)
│   ├── routers/
│   │   ├── companies.py         # CRUD + detail view
│   │   ├── dashboard.py         # Portfolio aggregation
│   │   ├── digest.py            # 501 stubs
│   │   ├── export.py            # 501 stubs
│   │   ├── files.py             # Signed URL download
│   │   ├── ingest.py            # Upload + dedup + Pub/Sub
│   │   ├── process.py           # Trigger processing, review
│   │   └── tasks.py             # Task CRUD + staleness check
│   ├── services/
│   │   ├── calculator.py        # Layer 1.5 deterministic formulas
│   │   ├── email_sender.py      # SendGrid with graceful degradation
│   │   ├── excel_parser.py      # openpyxl extraction
│   │   ├── firestore.py         # All Firestore operations
│   │   ├── health_scorer.py     # green/amber/red scoring
│   │   ├── llm.py               # Anthropic Claude client (tiered models)
│   │   ├── normaliser.py        # Full pipeline orchestrator
│   │   ├── pdf_parser.py        # pdfplumber extraction
│   │   ├── pubsub.py            # Pub/Sub publish + event handler
│   │   ├── storage.py           # GCS upload/download/signed URLs
│   │   └── validators.py        # Layer 3.5 sanity checks
│   └── static/                  # HTML/JS frontend pages
├── tests/                       # 22 test files, 242 tests
├── TEST_CARD.md                 # Testing-agent test card
├── Dockerfile
├── pyproject.toml
├── requirements.txt
└── .env.example
```

## What To Do Next

### Immediate (housekeeping):
1. **Commit uncommitted changes** — see command above
2. **Consider making repo public** — security scan showed no secrets, only Cloud Run URL with GCP project number in docs (minor, not exploitable)

### Phase 7 — Digest & Exports (next roadmap phase):
- Weekly portfolio digest email (aggregate health, key metrics, action items)
- Google Sheets export per company (formatted financial data)
- PDF report generation per digest
- All three endpoints currently return 501

### Phase 8 — Hardening:
- Redis/Memorystore caching for dashboard queries
- Rate limiting on public endpoints
- Retry with exponential backoff on GCP calls
- Structured logging + Cloud Monitoring alerts
- Load testing

### PE Comptroller Priority Hierarchy (discussed with Paul):
1. **Data accuracy** (60% of time) — Are the numbers right? Reconciliation, validation
2. **Trend detection** — Period-over-period variance, early warning signals
3. **LP reporting** — Clean, comparable metrics across portfolio
4. **Portfolio analytics** — Cross-company benchmarking, sector analysis

## Environment Setup

```bash
# Tests (no credentials needed)
python -m pytest tests/ -v --tb=short

# Local dev (needs credentials)
cp .env.example .env  # fill in: API_KEY, GCP_PROJECT_ID, ANTHROPIC_API_KEY
uvicorn app.main:app --reload --port 8080

# Required env vars for local/prod:
# API_KEY, GCP_PROJECT_ID, ANTHROPIC_API_KEY
# GCS_RAW_UPLOADS_BUCKET, GCS_REPORTS_BUCKET
# SENDGRID_API_KEY (optional), SENDGRID_FROM_EMAIL
```
