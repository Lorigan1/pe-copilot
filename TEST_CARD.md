# Test Card: PE CoPilot
> Last updated: 2026-03-01

## Project Overview
- **Description**: GCP-native financial data normalisation engine for private equity fund managers. Ingests heterogeneous financial reports (Excel, CSV, PDF) and produces unified, comparable metrics via a multi-layer AI pipeline.
- **Repository**: `https://github.com/Lorigan1/pe-copilot.git`
- **Tech Stack**
  - Frontend: Static HTML/JS (no framework) — upload form, portfolio dashboard, company detail
  - Backend: Python 3.12+, FastAPI 0.115+, Pydantic 2.10+
  - Database: Google Cloud Firestore (Native mode)
  - Storage: Google Cloud Storage (GCS)
  - Messaging: Google Cloud Pub/Sub
  - AI/LLM: Anthropic Claude API (Sonnet for extraction, Haiku for summarisation)
  - Email: SendGrid (optional — gracefully degrades when not configured)
  - External APIs: Anthropic Claude, SendGrid, Google Cloud Platform

---

## Environment Setup

### Run tests
```bash
cd pe-copilot
python -m pytest tests/ -v --tb=short
```

All tests are fully mocked — no GCP credentials, Anthropic API key, or SendGrid key required.

### Run locally (requires GCP credentials + Anthropic key)
```bash
cp .env.example .env   # then fill in real keys
uvicorn app.main:app --reload --port 8080
```

### Base URLs
- Local: `http://localhost:8080`
- Production: `https://pe-copilot-api-917934808232.europe-west2.run.app`

### Test Accounts
| Role          | Credential              | Value                      |
|---------------|-------------------------|----------------------------|
| API Key (dev) | `X-API-Key` header      | `test-key` (set in conftest.py) |
| API Key (prod)| `X-API-Key` header      | Set via `API_KEY` env var  |

### Required env vars (for local/prod — NOT needed for tests)
```
API_KEY=dev-api-key-change-me
GCP_PROJECT_ID=pe-copilot-dev
ANTHROPIC_API_KEY=sk-ant-...
GCS_RAW_UPLOADS_BUCKET=pe-copilot-raw-uploads
GCS_REPORTS_BUCKET=pe-copilot-reports
SENDGRID_API_KEY=SG...           # optional
SENDGRID_FROM_EMAIL=noreply@pecopilot.com
```

### Test configuration (pyproject.toml)
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = "-v --tb=short"
```

---

## Scope

### Critical Flows (must pass for any PASS verdict)
- [ ] **File ingestion pipeline**: Upload → GCS store → Firestore record → Pub/Sub publish (transactional with rollback)
- [ ] **Content deduplication**: SHA-256 hash check rejects duplicate file content with 409
- [ ] **Excel extraction**: openpyxl parses multi-sheet workbooks into pipe-separated text
- [ ] **CSV extraction**: pandas parses CSV exports correctly
- [ ] **PDF extraction**: pdfplumber extracts tables from multi-page PDFs
- [ ] **Layer 1.5 calculator**: Deterministic formula engine computes derived metrics (gross_profit, EBITDA, etc.)
- [ ] **Layer 2 normalisation**: Claude maps raw labels to canonical 9-metric schema
- [ ] **Layer 3 validation**: Missing metrics detected, period-over-period variances calculated
- [ ] **Layer 3.5 validators**: Sign constraints, accounting identities, magnitude bounds, variance spikes
- [ ] **Model tiering**: Sonnet used for extraction, Haiku for summarisation, max_tokens respected
- [ ] **Health scoring**: Staleness, variance, and missing metric checks produce correct green/amber/red
- [ ] **Health integration**: Normaliser calls health_scorer and updates company record in Firestore
- [ ] **Email alerts**: Health status changes trigger alert email (or log when SendGrid not configured)
- [ ] **File download**: Signed URL generation for original uploaded files
- [ ] **Company detail view**: Returns update history, metrics trends, pending tasks
- [ ] **Dashboard portfolio**: Returns aggregated company snapshots with health status
- [ ] **Staleness detection**: Cloud Scheduler endpoint creates tasks for overdue companies
- [ ] **API authentication**: All public endpoints require valid X-API-Key header

### API Surface
| Method | Endpoint                                | Auth Required | Status      |
|--------|-----------------------------------------|---------------|-------------|
| GET    | `/health`                               | No            | Implemented |
| GET    | `/`                                     | No            | Implemented |
| POST   | `/api/v1/ingest/upload`                 | Yes           | Implemented |
| POST   | `/api/v1/ingest/email`                  | Yes           | 501 (Phase 7) |
| GET    | `/api/v1/process/{update_id}/status`    | Yes           | Implemented |
| POST   | `/api/v1/process/{update_id}`           | Yes           | Implemented |
| POST   | `/api/v1/process/{update_id}/review`    | Yes           | Implemented |
| GET    | `/api/v1/companies`                     | Yes           | Implemented |
| GET    | `/api/v1/companies/{id}`                | Yes           | Implemented |
| POST   | `/api/v1/companies`                     | Yes           | Implemented |
| PUT    | `/api/v1/companies/{id}`                | Yes           | Implemented |
| GET    | `/api/v1/companies/{id}/detail`         | Yes           | Implemented |
| GET    | `/api/v1/dashboard/portfolio`           | Yes           | Implemented |
| GET    | `/api/v1/tasks`                         | Yes           | Implemented |
| POST   | `/api/v1/tasks`                         | Yes           | Implemented |
| PUT    | `/api/v1/tasks/{id}`                    | Yes           | Implemented |
| GET    | `/api/v1/files/download`                | Yes           | Implemented |
| POST   | `/api/v1/internal/process-event`        | No (IAM)      | Implemented |
| POST   | `/api/v1/internal/staleness-check`      | No (IAM)      | Implemented |
| POST   | `/api/v1/digest/generate`               | Yes           | 501 (Phase 7) |
| GET    | `/api/v1/digest/latest`                 | Yes           | 501 (Phase 7) |
| POST   | `/api/v1/export/sheets/{company_id}`    | Yes           | 501 (Phase 7) |
| POST   | `/api/v1/export/pdf/{digest_id}`        | Yes           | 501 (Phase 7) |

### Test Files (22 files, ~242 tests)
| File | Area | Tests |
|------|------|-------|
| `test_calculator.py` | Layer 1.5 formula engine | Calculation rules, label mappings, edge cases |
| `test_excel_parser.py` | Excel extraction | Multi-sheet, headers, formatting |
| `test_csv_parser.py` | CSV extraction | Flat files, encoding |
| `test_pdf_parser.py` | PDF extraction | Multi-page tables |
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
| `conftest.py` | Shared fixtures | Client, API key, env vars |

### Out of Scope
- Phase 7 endpoints: digest generation, Google Sheets export, PDF report export (all return 501)
- Email ingestion endpoint (`POST /api/v1/ingest/email`) — returns 501
- Actual SendGrid email delivery (only logic and graceful degradation are tested)
- Actual GCP service calls (all mocked — no credentials required)
- Actual Anthropic API calls (all mocked)
- Frontend UI testing (HTML/JS pages are not tested — backend API only)
- CI/CD pipeline and Docker build

---

## Regression Checklist
> Items from past bugs. These areas have broken before and should be watched closely.

- [ ] **NorthStar cash flow sign convention** — Costs stored as negative in Sage. Calculator must subtract (not add) negative values. Previously produced wrong gross_profit.
- [ ] **Ingest transaction mocks** — When new async methods are added to `firestore_service` (like `find_duplicate_update`), all ingest tests must mock them as `AsyncMock(return_value=None)` or they fail with `TypeError: object MagicMock can't be used in 'await'`.
- [ ] **BrightPath positive cost convention** — Xero stores costs as positive numbers. Calculation rules use `subtract` instead of `add`. Mixing up conventions produces doubled costs.
- [ ] **Helix PDF multi-table parsing** — Tables span pages 3-5. Parser must handle cross-page table continuation.
- [ ] **Duplicate file detection** — Dedup is content-based (SHA-256), not filename-based. Same content with different filenames must still be caught.
- [ ] **Layer 3.5 vs processing status** — `NEEDS_REVIEW` set by validators must not be overridden by the subsequent confidence/missing-metrics check in the normaliser.
- [ ] **Numbered list restart in docx** — Each section's numbered list needs a separate numbering reference or lists continue from previous sections.

---

## Pass / Fail Criteria

**PASS**: All 242 tests pass. No CRITICAL or HIGH findings. Test execution completes in under 10 seconds.

**PASS WITH WARNINGS**: All tests pass. MEDIUM or LOW findings only (e.g. deprecation warnings, slow tests).

**FAIL**: One or more tests fail, OR any CRITICAL or HIGH finding exists (e.g. broken pipeline, auth bypass, data corruption).

---

## Running Tests

```bash
# Full suite
python -m pytest tests/ -v --tb=short

# Specific area
python -m pytest tests/test_validators.py -v
python -m pytest tests/test_dedup.py tests/test_ingest_transaction.py -v

# With coverage
python -m pytest tests/ --cov=app --cov-report=term-missing
```
