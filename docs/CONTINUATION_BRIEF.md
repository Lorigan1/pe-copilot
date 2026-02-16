# PE CoPilot — Continuation Brief

Paste this into a new chat session to resume work on PE CoPilot. See "What else to paste" at the bottom.

---

## Project overview

PE CoPilot is a GCP-native financial data normalisation engine for private equity fund managers. It ingests heterogeneous financial reports (Excel, CSV, PDF) from portfolio companies and produces unified, comparable metrics through a 3 + 1.5 layer pipeline.

**Tech stack:** Python 3.12, FastAPI, Pydantic, GCP (Cloud Run, Firestore, Cloud Storage, Pub/Sub, Cloud Scheduler), Anthropic Claude, Docker.

**Repo:** `https://github.com/Lorigan1/pe-copilot.git`

---

## Architecture

### Processing pipeline

```
Raw file → Layer 1 (extract text) → Layer 1.5 (deterministic calc) → Layer 2 (Claude normalise) → Layer 3 (validate + summarise)
```

- **Layer 1**: openpyxl (Excel), pandas (CSV), pdfplumber (PDF) → pipe-separated text
- **Layer 1.5**: `calculator.py` — applies company-specific formulas, fills blank cells, marks `[COMPUTED]`
- **Layer 2**: Claude **Sonnet** maps raw labels to canonical metrics (9: revenue, gross_profit, ebitda, net_income, cash_balance, total_debt, net_assets, operating_cashflow, headcount)
- **Layer 3**: Pydantic validation, variance calculation vs previous period
- **Layer 3.5**: Deterministic sanity checks (`validators.py`) — sign constraints, accounting identities, magnitude bounds, zero-revenue check, variance spike detection
- **Summarisation**: Claude **Haiku** (cheaper model) writes executive summary, risks, action items from structured data

### Event-driven processing

```
Upload → GCS → Firestore → Pub/Sub → Cloud Run internal endpoint → process
```

Transaction safety: GCS cleanup on Firestore failure, graceful Pub/Sub degradation (upload succeeds even if publish fails).

Content-based deduplication: SHA-256 hash of file bytes checked before upload. Duplicate files rejected with 409 Conflict.

### Key files

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI app, 7 routers + internal router |
| `app/config.py` | Pydantic settings from env vars |
| `app/services/normaliser.py` | Core 3-layer pipeline orchestration |
| `app/services/calculator.py` | Layer 1.5 — formula engine |
| `app/services/storage.py` | GCS with retries, logging, custom exceptions |
| `app/services/pubsub.py` | Pub/Sub publisher |
| `app/services/firestore.py` | Firestore CRUD |
| `app/services/llm.py` | Anthropic API wrapper (cache, retry, model routing) |
| `app/services/validators.py` | Layer 3.5 — deterministic financial sanity checks |
| `app/services/excel_parser.py` | Layer 1 Excel extraction |
| `app/services/pdf_parser.py` | Layer 1 PDF extraction |
| `app/routers/ingest.py` | File upload (dedup check + 3-step transactional) |
| `app/routers/process.py` | Processing trigger + status polling |
| `app/routers/tasks.py` | Task CRUD + internal router (Pub/Sub handler, staleness check) |
| `app/routers/companies.py` | Company CRUD |
| `app/routers/dashboard.py` | Portfolio aggregation |
| `app/static/upload.html` | Upload form with drag-drop and polling |
| `app/static/dashboard.html` | Portfolio dashboard |
| `app/static/company-detail.html` | Company detail drilldown page |
| `scripts/seed_data.py` | Seeds funds, companies, label_mappings, calculation_rules into Firestore |
| `scripts/clear_updates.py` | Clears all update records from Firestore (for fresh testing) |

### Models

| Model | Key fields |
|-------|-----------|
| `Update` | id, fund_id, company_id, processing_status, normalised_metrics, variances, summary, risks, action_items, confidence |
| `Company` | id, fund_id, name, sector, accounting_system, canonical_metrics, label_mappings, calculation_rules, mapping_instructions |
| `Fund` | id, name, manager, settings (digest_frequency, staleness_thresholds, variance_threshold) |
| `Task` | id, fund_id, company_id, description, priority, status, assigned_to |

---

## Current state (as of this session)

### What's been built and tested

1. **NorthStar Logistics** (Sage, Excel) — full pipeline working. Cash flow discrepancy fixed. 5 calculation rules (gross_profit, total_overheads, ebitda, operating_profit, pbt). Costs stored as negative.

2. **BrightPath Education** (Xero, CSV) — full pipeline working. 3 calculation rules (gross_profit, ebitda, net_income). Costs stored as positive (subtract instead of add).

3. **Helix Manufacturing** (QuickBooks, PDF) — full pipeline working. 4 calculation rules (gross_profit, ebitda, net_income, total_debt). Multi-table PDF parsing across pages 3-5.

4. **Upload form** — drag-drop file upload with auto-processing via Pub/Sub and status polling.

5. **GCP integration** — Pub/Sub event-driven processing, hardened storage with retries, transaction safety (GCS cleanup on Firestore failure), internal endpoints (process-event, staleness-check).

6. **Variance calculation** — period-over-period % change, fed into Claude summarisation.

7. **Company detail view** — clickable dashboard cards drill down into company profile, metrics with variances, trend history, risks/action items, update timeline, and pending tasks.

8. **Content-based deduplication** — SHA-256 hash of uploaded file bytes, checked against Firestore before creating a new update. Returns 409 Conflict for duplicate files regardless of filename.

9. **Model tiering** — Sonnet for financial data extraction (Layer 2), Haiku for summarisation. Cuts ~40-50% off token cost without sacrificing extraction accuracy. `max_tokens` also reduced for summarisation (2048 vs 4096).

10. **Layer 3.5 financial validation** — deterministic sanity checks on LLM output: sign constraints (revenue >= 0), accounting identities (gross_profit <= revenue), magnitude bounds (> £10B = likely unit error), zero-revenue check, variance spike detection (> 500%). Warnings passed to summarisation context.

11. **Test suite** — 224 tests all passing (calculator, parsers, pipeline, storage, Pub/Sub, transaction safety, staleness, company detail, deduplication, validators, model tiering).

### Deployment status

Everything is deployed to Cloud Run. Pub/Sub topic, push subscription, and Cloud Scheduler job are all configured. See `docs/GCP_INTEGRATION.md` for details.

### What's NOT been built yet (future phases)

- **Email ingestion** (`POST /api/v1/ingest/email`) — accept reports via email
- **Digest generation** — weekly/monthly email summaries
- **Export** — Google Sheets and PDF report export
- **OCR** — scanned PDF support
- **Additional portfolio companies** — only 3 companies configured so far

---

## Test data

| Company | File | Type | Period |
|---------|------|------|--------|
| NorthStar Logistics | `testdata/NorthStar_Logistics_Jan2026.xlsx` | Excel | Jan 2026 |
| NorthStar Logistics | `testdata/NorthStar_Logistics_Feb2026.xlsx` | Excel | Feb 2026 |
| BrightPath Education | `testdata/BrightPath_Education_Jan2026.csv` | CSV | Jan 2026 |
| Helix Manufacturing | `testdata/Helix_Manufacturing_Q4_2025.pdf` | PDF | Q4 2025 |

## Company IDs (Firestore)

| Company | ID | Fund ID |
|---------|----|----|
| NorthStar Logistics | `3kRa7txt35WweOzO6LL6` | `OprI9mdcmQ9ZplIbzS0n` |
| BrightPath Education | `L6UNvXfxNuCC7cKEJ2Ku` | `OprI9mdcmQ9ZplIbzS0n` |
| Helix Manufacturing | `IpO2rgie3TdoldUcQXE7` | `OprI9mdcmQ9ZplIbzS0n` |

**Fund:** Meridian Capital Fund III

---

## Documentation

| File | Contents |
|------|----------|
| `docs/SETUP.md` | Full setup from scratch (GCP project, Firestore, GCS, IAM, CI/CD) |
| `docs/USAGE.md` | Day-to-day usage, API reference, operations guide |
| `docs/GCP_INTEGRATION.md` | Pub/Sub, Cloud Scheduler, storage hardening, transaction safety |
| `docs/SESSION_WORK.md` | Detailed record of calculation rules, upload form, and all changes |
| `docs/PE_CoPilot_System_Guide.docx` | Non-technical guide to the architecture, AI integration, and what's been built |
| `PLAN.md` | Implementation plan for calculation rules + upload form session |

---

## What else to paste into the new session

For the best result, paste into the new chat in this order:

1. **This continuation brief** (required)
2. **The implementation plan** (`PLAN.md`) if you want context on what was planned vs built
3. **Any new requirements or tasks** you want to work on next

### Optionally, if relevant to the next task:

- **`docs/GCP_INTEGRATION.md`** — if working on deployment or Pub/Sub issues
- **`docs/SETUP.md`** — if setting up a new environment or debugging infrastructure
- **`app/services/calculator.py`** — if modifying calculation logic or adding a new company
- **`app/services/normaliser.py`** — if changing the processing pipeline
- **`scripts/seed_data.py`** — if adding a new portfolio company

### What NOT to paste (too large, just let the new session read the files):

- Test files (1000+ lines each)
- `storage.py`, `firestore.py` (let the session read them as needed)
- Static HTML files

The new session can read any file in the repo directly, so only paste what gives essential context upfront. The brief above gives enough for the AI to understand the project and pick up work immediately.
