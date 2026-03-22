# GCP Deployment (Backend + vLLM + Analytics Job)

Deployment is split into independent workloads:
- `ketchup-backend` (Cloud Run service)
- `ketchup-vllm` (Cloud Run service or GPU node exposing OpenAI-compatible `/v1`)
- `ketchup-analytics-materialization` (Cloud Run Job, scheduler-triggered)

## 1) Required APIs

```bash
gcloud services enable \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  sqladmin.googleapis.com \
  storage.googleapis.com
```

## 2) Secrets

Create runtime secrets:

```bash
printf "%s" "$DATABASE_URL"         | gcloud secrets create DATABASE_URL --data-file=-
printf "%s" "$GOOGLE_MAPS_API_KEY" | gcloud secrets create GOOGLE_MAPS_API_KEY --data-file=-
printf "%s" "$TAVILY_API_KEY"      | gcloud secrets create TAVILY_API_KEY --data-file=-
printf "%s" "$VLLM_API_KEY"        | gcloud secrets create VLLM_API_KEY --data-file=-
printf "%s" "$BACKEND_INTERNAL_API_KEY" | gcloud secrets create BACKEND_INTERNAL_API_KEY --data-file=-
printf "%s" "$HF_TOKEN"            | gcloud secrets create HF_TOKEN --data-file=-
```

## 3) Deploy vLLM

Serve an OpenAI-compatible endpoint.
If using vLLM tool-calling:
- `--enable-auto-tool-choice`
- `--tool-call-parser hermes` (or parser matching model/template)

Build and push the model-serving image to Artifact Registry:

```bash
ENVIRONMENT="${ENVIRONMENT:-dev}"
./scripts/push_vllm_image.sh "$PROJECT_ID" "$REGION" "ketchup-vllm-${ENVIRONMENT}" "qwen3-4b-2507-vllm"
```

Equivalent Cloud Build invocation:

```bash
gcloud builds submit \
  --config vllm/cloudbuild.yaml \
  --substitutions _LOCATION="$REGION",_REPO="ketchup-vllm-${ENVIRONMENT}",_NAME="qwen3-4b-2507-vllm"
```

Capture URL:

```bash
VLLM_URL="$(gcloud run services describe ketchup-vllm --region "$REGION" --format='value(status.url)')"
echo "$VLLM_URL"
```

## 4) Deploy Backend

Backend environment:
- `DATABASE_URL` (Cloud SQL Postgres)
- `VLLM_BASE_URL=${VLLM_URL}/v1` for the backend application runtime
- `VLLM_MODEL=<served-model-name>`
- `VLLM_API_KEY`
- `GOOGLE_MAPS_API_KEY`
- `TAVILY_API_KEY`
- `BACKEND_INTERNAL_API_KEY`

## 5) Deploy Analytics Job

Run `python scripts/materialize_analytics.py` inside a Cloud Run Job image.
Schedule via Cloud Scheduler (daily or desired cadence).

Terraform path:
- `terraform/analytics_job.tf`
- `terraform/variables.tf`
- `terraform/terraform.tfvars.example`

## 6) Deploy vLLM to Cloud Run for GitHub Actions

The evaluation workflow in [`.github/workflows/model-pipeline.yml`](/Users/vigneshraja/Documents/NEU Notes/MLOps/Project/ketchup-backend/.github/workflows/model-pipeline.yml) is designed to run on GitHub-hosted runners and call a deployed vLLM endpoint over HTTPS.

### One-time setup

1. Install and authenticate the Google Cloud CLI locally.
2. Create a Secret Manager secret named `HF_TOKEN` containing a Hugging Face token that can download the model.
3. Choose a region with Cloud Run GPU capacity and quota, for example `us-central1`.

Create the HF token secret:

```bash
printf "%s" "$HF_TOKEN" | gcloud secrets create HF_TOKEN --data-file=-
```

### Deploy command

Use the helper script in this repo:

```bash
GCLOUD_BIN="$HOME/google-cloud-sdk/bin/gcloud" \
./scripts/deploy_vllm_cloud_run.sh YOUR_PROJECT_ID us-central1
```

Defaults:
- Cloud Run service: `ketchup-vllm`
- Artifact Registry repo: `ketchup-vllm-dev`
- Image name: `qwen3-4b-2507-vllm`
- GPU: `nvidia-l4`
- CPU / memory: `8` / `32Gi`
- Public access: enabled for quick GitHub Actions testing
- Min instances: `0`
- Max instances: `1`

Override behavior with env vars when needed:

```bash
ALLOW_PUBLIC=false \
MAX_INSTANCES=2 \
VLLM_MAX_NUM_SEQS=8 \
./scripts/deploy_vllm_cloud_run.sh YOUR_PROJECT_ID us-central1
```

### GitHub Actions variables

After deploy, set these in GitHub -> Settings -> Secrets and variables -> Actions -> Variables:

- `VLLM_BASE_URL`: the Cloud Run service root URL, for example `https://ketchup-vllm-abc123-uc.a.run.app`
- `VLLM_HEALTH_URL`: the health endpoint, for example `https://ketchup-vllm-abc123-uc.a.run.app/health`
- `VLLM_MODEL`: served model name, for example `Qwen/Qwen3-4B-Instruct-2507`

Important:
- For this workflow, `VLLM_BASE_URL` should be the service root without `/v1`.
- The evaluation scripts append `/v1/models` and `/v1/chat/completions` internally.
- If you keep the Cloud Run service private, the GitHub workflow will also need Google authentication added before the health-check and evaluation steps.

### What the workflow does

1. Runs on `ubuntu-latest`
2. Verifies `VLLM_BASE_URL` and `VLLM_HEALTH_URL` are configured
3. Waits for the deployed vLLM service to become healthy
4. Runs `dvc repro model_bias_eval model_bias_slices model_bias_fairlearn`
5. Runs `python scripts/evaluate_tool_calling_bfcl.py`
6. Uploads generated reports as GitHub Actions artifacts

## 7) Verify

Backend:

```bash
curl "${BACKEND_URL}/health"
```

vLLM:

```bash
curl "${VLLM_URL}/health"
curl "${VLLM_URL}/v1/models"
```

Analytics status endpoint (internal key required):

```bash
curl -H "X-Internal-Auth: ${BACKEND_INTERNAL_API_KEY}" \
  "${BACKEND_URL}/api/internal/analytics/status"
```

Planner path check:
- Generate/refine plans for a real group.
- Confirm plans include `logistics.analytics` metadata.
- Confirm backend logs show tool usage and no schema parse failures.
