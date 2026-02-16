# PE CoPilot — GCP Integration Guide

How to set up Pub/Sub event-driven processing, Cloud Scheduler staleness checks, and hardened storage — from scratch or on an existing deployment.

---

## What this covers

| Feature | Purpose |
|---------|---------|
| Pub/Sub file ingestion events | Auto-trigger processing after upload (no more dual HTTP calls) |
| Hardened Cloud Storage | Retries, logging, custom exceptions, integrity verification |
| Transaction safety | GCS cleanup if Firestore fails, graceful Pub/Sub degradation |
| Internal endpoints | Pub/Sub push handler + Cloud Scheduler staleness check |
| Status polling | Frontend polls for completion instead of blocking |

---

## Prerequisites

Everything in `docs/SETUP.md` must be completed first. You should have:

- A working Cloud Run deployment
- Firestore database in `europe-west2`
- GCS buckets (`pe-copilot-dev-raw-uploads`, `pe-copilot-dev-reports`)
- Service account with existing IAM roles

---

## 1. Enable the Pub/Sub API

```bash
gcloud services enable pubsub.googleapis.com --project=pe-copilot-dev
```

---

## 2. Create the Pub/Sub topic

```bash
gcloud pubsub topics create file-ingestion-events --project=pe-copilot-dev
```

Verify:

```bash
gcloud pubsub topics list --project=pe-copilot-dev
```

---

## 3. Grant the service account Pub/Sub permissions

```bash
PROJECT_ID=$(gcloud config get-value project)
SA="pe-copilot-api@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA}" \
  --role="roles/pubsub.publisher"
```

---

## 4. Build and deploy the updated Cloud Run service

```bash
PROJECT_ID=$(gcloud config get-value project)
REGION=europe-west2
VERSION=v2  # increment from your current version
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/pe-copilot/pe-copilot-api:${VERSION}"

gcloud auth configure-docker ${REGION}-docker.pkg.dev

# Build for linux/amd64 (required for Cloud Run, even on Apple Silicon Macs)
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

---

## 5. Create the Pub/Sub push subscription

The push subscription sends an HTTP POST to your Cloud Run service whenever a message is published to the topic.

```bash
PROJECT_ID=$(gcloud config get-value project)
SA="pe-copilot-api@${PROJECT_ID}.iam.gserviceaccount.com"
CLOUD_RUN_URL=$(gcloud run services describe pe-copilot-api --region=europe-west2 --format='value(status.url)')

gcloud pubsub subscriptions create file-ingestion-sub \
  --topic=file-ingestion-events \
  --push-endpoint="${CLOUD_RUN_URL}/api/v1/internal/process-event" \
  --push-auth-service-account="${SA}" \
  --ack-deadline=300 \
  --project=$PROJECT_ID
```

The `--ack-deadline=300` gives the processing endpoint 5 minutes to complete before Pub/Sub retries. The `--push-auth-service-account` adds an OIDC token to each push request so Cloud Run can verify the caller.

Verify:

```bash
gcloud pubsub subscriptions list --project=$PROJECT_ID
```

---

## 6. Create the Cloud Scheduler job

Cloud Scheduler calls the staleness-check endpoint daily to find companies with outdated data and create follow-up tasks.

```bash
PROJECT_ID=$(gcloud config get-value project)
SA="pe-copilot-api@${PROJECT_ID}.iam.gserviceaccount.com"
CLOUD_RUN_URL=$(gcloud run services describe pe-copilot-api --region=europe-west2 --format='value(status.url)')

gcloud scheduler jobs create http staleness-check-daily \
  --location=europe-west2 \
  --schedule="0 2 * * *" \
  --time-zone="Europe/London" \
  --http-method=POST \
  --uri="${CLOUD_RUN_URL}/api/v1/internal/staleness-check" \
  --oidc-service-account-email="${SA}" \
  --project=$PROJECT_ID
```

This runs at 2:00 AM London time every day. To check a specific fund, append `?fund_id=your-fund-id` to the URI.

Verify the job exists:

```bash
gcloud scheduler jobs list --location=europe-west2 --project=$PROJECT_ID
```

Test it manually:

```bash
gcloud scheduler jobs run staleness-check-daily --location=europe-west2 --project=$PROJECT_ID
```

---

## 7. Verify the full pipeline

### 7.1 Upload triggers auto-processing

1. Open the upload form at `https://your-cloud-run-url/upload`
2. Upload a file — the form should show "Processing will begin automatically"
3. The progress bar polls for completion instead of making a separate process call

### 7.2 Check Cloud Run logs for the 3-step flow

```bash
gcloud run services logs read pe-copilot-api --region=europe-west2 --limit=30
```

You should see (in order):

1. `File uploaded to GCS: gs://...`
2. `Firestore update record created: upd-...`
3. `Published file ingestion event ... message_id=...`
4. `Processing event for update upd-...` (from the Pub/Sub push callback)

### 7.3 Verify staleness check

```bash
CLOUD_RUN_URL=$(gcloud run services describe pe-copilot-api --region=europe-west2 --format='value(status.url)')

curl -X POST "${CLOUD_RUN_URL}/api/v1/internal/staleness-check?fund_id=YOUR_FUND_ID"
```

Response:

```json
{"tasks_created": 1, "companies_checked": 5}
```

### 7.4 Run the test suite

```bash
pip install ".[dev]"
python -m pytest tests/ -v
```

All 187 tests should pass, including the 45 new ones covering storage hardening, Pub/Sub, transaction safety, and staleness checks.

---

## Architecture: how the pieces fit together

```
Upload Form
    │
    ▼
POST /api/v1/ingest/upload
    │
    ├── Step 1: Upload to GCS (with retries)
    │
    ├── Step 2: Create Firestore record
    │   └── On failure → clean up GCS file
    │
    └── Step 3: Publish to Pub/Sub (non-blocking)
        └── On failure → log warning, upload still succeeds
                │
                ▼
        Pub/Sub push subscription
                │
                ▼
        POST /api/v1/internal/process-event
                │
                ▼
        normaliser_service.process_update()


Cloud Scheduler (daily 2am)
        │
        ▼
POST /api/v1/internal/staleness-check
        │
        ▼
For each company:
    → Check last completed update age
    → If stale → create high-priority Task
```

---

## Staleness thresholds

| Reporting frequency | Threshold (days) |
|---------------------|------------------|
| monthly             | 35               |
| quarterly           | 100              |
| annually            | 380              |
| varies              | 60               |
| unknown/other       | 60 (default)     |

A company is "stale" if its most recent completed update is older than the threshold for its reporting frequency, or if it has no completed updates at all.

---

## New files and changes

| File | Change | Purpose |
|------|--------|---------|
| `pyproject.toml` | Modified | Added `google-cloud-pubsub>=2.23.0` |
| `app/config.py` | Modified | Added `pubsub_file_ingestion_topic` setting |
| `app/services/storage.py` | Rewritten | Retries, logging, custom exceptions, `delete_file()` |
| `app/services/pubsub.py` | New | Pub/Sub publisher service |
| `app/routers/ingest.py` | Modified | 3-step transactional flow with Pub/Sub trigger |
| `app/routers/tasks.py` | Modified | Added `internal_router` with process-event and staleness-check |
| `app/routers/process.py` | Modified | Added `GET /{update_id}/status` for polling |
| `app/main.py` | Modified | Registered `internal_router` |
| `app/static/upload.html` | Modified | Replaced manual process call with status polling |
| `tests/test_storage.py` | New | 16 tests — exceptions, URL parsing, retry config |
| `tests/test_pubsub.py` | New | 5 tests — message format, publish, errors, timeout |
| `tests/test_ingest_transaction.py` | New | 9 tests — transaction safety, process-event endpoint |
| `tests/test_staleness.py` | New | 11 tests — thresholds, staleness logic, task creation |

---

## Storage hardening details

The storage service (`app/services/storage.py`) now includes:

- **Custom exceptions**: `StorageError`, `StorageUploadError`, `StorageDownloadError` — each carries `bucket` and `blob_path` context
- **Exponential backoff retries**: 1s initial delay, 2x multiplier, 32s max delay, 180s deadline. Retries on `ConnectionError`, `TimeoutError`, `ServiceUnavailable`, `TooManyRequests`, `InternalServerError`
- **Upload integrity verification**: After upload, calls `blob.reload()` + `blob.exists()` to confirm the blob landed
- **Structured logging**: Every operation logs start, success, and failure with file paths and sizes
- **`delete_file(gcs_url)`**: Parses `gs://bucket/path` URLs, silently handles `NotFound` (idempotent cleanup)

---

## Transaction safety

The upload endpoint (`POST /api/v1/ingest/upload`) follows a strict 3-step sequence:

1. **GCS upload** — if this fails, return 500 immediately (nothing to clean up)
2. **Firestore record** — if this fails, delete the GCS file that was just uploaded, then return 500
3. **Pub/Sub publish** — if this fails, log a warning but return 201 (the update stays PENDING and can be reprocessed manually)

This ensures no orphaned GCS files without Firestore records, and no lost uploads due to Pub/Sub outages.

---

## Troubleshooting

### Pub/Sub messages not arriving

Check the subscription exists and points to the correct endpoint:

```bash
gcloud pubsub subscriptions describe file-ingestion-sub --project=pe-copilot-dev
```

Check for undelivered messages:

```bash
gcloud pubsub subscriptions pull file-ingestion-sub --auto-ack --limit=5 --project=pe-copilot-dev
```

### Processing stuck in PENDING

If Pub/Sub failed after upload, the update stays PENDING. Reprocess manually:

```bash
CLOUD_RUN_URL=$(gcloud run services describe pe-copilot-api --region=europe-west2 --format='value(status.url)')

curl -X POST "${CLOUD_RUN_URL}/api/v1/process/UPDATE_ID" \
  -H "X-API-Key: your-key"
```

### Cloud Scheduler job not firing

```bash
gcloud scheduler jobs describe staleness-check-daily --location=europe-west2 --project=pe-copilot-dev
```

Check the `lastAttemptTime` and `status` fields. If the OIDC token is failing, verify the service account has `roles/run.invoker` on the Cloud Run service.

### Storage retries exhausting

If uploads consistently fail after retries (180s deadline), check:

```bash
gcloud run services logs read pe-copilot-api --region=europe-west2 --limit=50 | grep "StorageUploadError"
```

Common causes: bucket permissions, wrong region, bucket doesn't exist.

---

## Cost estimate (additional)

| Service | Free tier | Typical dev cost |
|---------|-----------|------------------|
| Pub/Sub | 10 GB/month | £0 |
| Cloud Scheduler | 3 jobs free | £0 |

These additions stay within GCP free tier for development workloads.
