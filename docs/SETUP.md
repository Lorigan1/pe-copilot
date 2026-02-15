# PE CoPilot — Setup & Reproducibility Guide

How to go from a fresh clone to a running instance, locally and in the cloud.

---

## Prerequisites

You need these installed on your machine:

|       Tool       |                  Install                   |       Verify        |
|------------------|--------------------------------------------|---------------------|
| Python 3.12+     | `brew install python@3.12`                 | `python3 --version` |
| Docker Desktop   | https://docker.com/products/docker-desktop | `docker --version`  |
| Google Cloud CLI | `brew install google-cloud-sdk`            | `gcloud --version`  |
| GitHub CLI       | `brew install gh`                          | `gh --version`      |
| Git              | Comes with macOS / `brew install git`      | `git --version`     |

---

## 1. Clone the repo

```bash
git clone https://github.com/Lorigan1/pe-copilot.git
cd pe-copilot
```

---

## 2. GCP project setup

### 2.1 Create project and enable billing

```bash
gcloud projects create pe-copilot-dev --name="PE CoPilot"
gcloud config set project pe-copilot-dev

# Link billing (get ACCOUNT_ID from: gcloud billing accounts list)
gcloud billing projects link pe-copilot-dev --billing-account=ACCOUNT_ID
```

### 2.2 Enable required APIs

```bash
gcloud services enable \
  firestore.googleapis.com \
  run.googleapis.com \
  storage.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  compute.googleapis.com
```

### 2.3 Create Firestore database

```bash
gcloud firestore databases create \
  --location=europe-west2 \
  --type=firestore-native
```

Location cannot be changed after creation. Use `europe-west2` (London) for UK, `us-central1` for US.

### 2.4 Create Cloud Storage buckets

```bash
PROJECT_ID=$(gcloud config get-value project)

gcloud storage buckets create gs://${PROJECT_ID}-raw-uploads \
  --location=europe-west2 \
  --uniform-bucket-level-access

gcloud storage buckets create gs://${PROJECT_ID}-reports \
  --location=europe-west2 \
  --uniform-bucket-level-access
```

### 2.5 Create Artifact Registry repository

```bash
gcloud artifacts repositories create pe-copilot \
  --repository-format=docker \
  --location=europe-west2 \
  --description="PE CoPilot container images"
```

### 2.6 Create service account

```bash
PROJECT_ID=$(gcloud config get-value project)

gcloud iam service-accounts create pe-copilot-api \
  --display-name="PE CoPilot API"

SA="pe-copilot-api@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA}" \
  --role="roles/artifactregistry.writer"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA}" \
  --role="roles/run.admin"

gcloud iam service-accounts add-iam-policy-binding ${SA} \
  --member="serviceAccount:${SA}" \
  --role="roles/iam.serviceAccountUser"
```

### 2.7 Set up Workload Identity Federation (for GitHub Actions CI/CD)

```bash
PROJECT_ID=$(gcloud config get-value project)
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')

gcloud iam workload-identity-pools create "github-pool" \
  --location="global" \
  --display-name="GitHub Actions Pool"

# Replace YOUR_GITHUB_USERNAME/pe-copilot with your repo
gcloud iam workload-identity-pools providers create-oidc "github-provider" \
  --location="global" \
  --workload-identity-pool="github-pool" \
  --display-name="GitHub Provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='YOUR_GITHUB_USERNAME/pe-copilot'" \
  --issuer-uri="https://token.actions.githubusercontent.com"

gcloud iam service-accounts add-iam-policy-binding \
  "pe-copilot-api@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/attribute.repository/YOUR_GITHUB_USERNAME/pe-copilot"
```

Note the two values you'll need for GitHub secrets:

```bash
echo "WIF_PROVIDER: projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/providers/github-provider"
echo "WIF_SERVICE_ACCOUNT: pe-copilot-api@${PROJECT_ID}.iam.gserviceaccount.com"
```

### 2.8 Create Firestore composite indexes

These are required for the app's multi-field queries:

```bash
# Updates: fund_id + company_id + received_at (dashboard query)
gcloud firestore indexes composite create \
  --collection-group=updates \
  --field-config=field-path=fund_id,order=ascending \
  --field-config=field-path=company_id,order=ascending \
  --field-config=field-path=received_at,order=descending

# Updates: company_id + processing_status + received_at (previous update lookup)
gcloud firestore indexes composite create \
  --collection-group=updates \
  --field-config=field-path=company_id,order=ascending \
  --field-config=field-path=processing_status,order=ascending \
  --field-config=field-path=received_at,order=descending

# Tasks: company_id + status (pending tasks count)
gcloud firestore indexes composite create \
  --collection-group=tasks \
  --field-config=field-path=company_id,order=ascending \
  --field-config=field-path=status,order=ascending
```

---

## 3. GitHub setup

### 3.1 Create repo and push

```bash
gh repo create pe-copilot --private --source=. --remote=origin --push
```

### 3.2 Add repository secrets

Go to GitHub → repo Settings → Secrets and variables → Actions → New repository secret:

| Secret | Value |
|---|---|
| `GCP_PROJECT_ID` | Your GCP project ID (e.g. `pe-copilot-dev`) |
| `WIF_PROVIDER` | From step 2.7 |
| `WIF_SERVICE_ACCOUNT` | From step 2.7 |
| `ANTHROPIC_API_KEY` | From https://console.anthropic.com |

### 3.3 Verify setup

```bash
bash scripts/check_github_setup.sh
```

---

## 4. Local development

### 4.1 Create .env file

```bash
cp .env.example .env
```

Edit `.env` with your values:

```
DEBUG=true
API_KEY=your-local-dev-key
GCP_PROJECT_ID=pe-copilot-dev
GCP_REGION=europe-west2
GCS_RAW_UPLOADS_BUCKET=pe-copilot-dev-raw-uploads
GCS_REPORTS_BUCKET=pe-copilot-dev-reports
ANTHROPIC_API_KEY=sk-ant-your-key
```

### 4.2 Authenticate for local Firestore/GCS access

```bash
gcloud auth application-default login
```

### 4.3 Build and run with Docker

```bash
docker build -t pe-copilot .
docker run -p 8080:8080 --env-file .env pe-copilot
```

### 4.4 Verify

- http://localhost:8080/health → `{"status": "healthy"}`
- http://localhost:8080/docs → Swagger UI

### 4.5 Seed test data

```bash
pip install -e .
python -m scripts.seed_data
```

### 4.6 Run tests

```bash
pip install ".[dev]"
python -m pytest tests/ -v
```

---

## 5. Deploy to Cloud Run

```bash
PROJECT_ID=$(gcloud config get-value project)
REGION=europe-west2
VERSION=v1  # increment for each deploy
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/pe-copilot/pe-copilot-api:${VERSION}"

# Authenticate Docker
gcloud auth configure-docker ${REGION}-docker.pkg.dev

# Build for linux/amd64 (required for Cloud Run, even on Apple Silicon Macs)
docker build --platform linux/amd64 --no-cache -t $IMAGE .
docker push $IMAGE

# Deploy
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

**Important:** Always use `--platform linux/amd64` on Apple Silicon Macs. Always use `--no-cache` when static files have changed (Docker caches the `COPY app/ app/` layer aggressively).

---

## 6. Troubleshooting

### "The query requires an index"
Firestore needs composite indexes for multi-field queries. The error message includes a link — click it to create the index. See step 2.8 for all required indexes.

### Docker build uses cached files
Use `--no-cache` flag: `docker build --platform linux/amd64 --no-cache -t $IMAGE .`

### Cloud Run: "must support amd64/linux"
Add `--platform linux/amd64` to the docker build command.

### "model not found" from Anthropic
Check the model string in `app/config.py`. Current correct values: `claude-sonnet-4-5-20250929` (normalisation/summarisation), `claude-haiku-4-5-20251001` (fast/classification).

### Check Cloud Run logs
```bash
gcloud run services logs read pe-copilot-api --region=europe-west2 --limit=20
```

---

## Cost estimate

| Service | Free tier | Typical dev cost |
|---|---|---|
| Firestore | 1 GB storage, 50K reads/day | £0 |
| Cloud Storage | 5 GB, 5K ops/day | £0 |
| Cloud Run | 2M requests/month, 360K vCPU-sec | £0 |
| Artifact Registry | 500 MB | £0 |
| Anthropic API | No free tier | ~£0.003 per normalisation call |

GCP bill during development will likely be £0. Anthropic is pay-per-call.
