# Qwen3-4B-Instruct-2507 on Cloud Run (L4 GPU) with vLLM + Tool Calling (Maps + Web Search)

## 0) Vars
```bash
export PROJECT_ID="$(gcloud config get-value project)"
export REGION="us-east4"                   # use your region
export SERVICE_NAME="qwen3-4b-2507-vllm-tools"
export RUN_SA_EMAIL="YOUR_RUN_SA@${PROJECT_ID}.iam.gserviceaccount.com"
export AR_REPO_NAME="qwen3-vllm-repo"
export IMAGE_NAME="qwen3-4b-2507-vllm-tools"
```

## 1) Enable APIs

```bash
gcloud services enable run.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com
```

## 2) Create secrets (HF + Maps + Web Search)

```bash
printf "%s" "$HF_TOKEN" | gcloud secrets create HF_TOKEN --data-file=-
printf "%s" "$MAPS_API_KEY" | gcloud secrets create MAPS_API_KEY --data-file=-
printf "%s" "$SERPER_API_KEY" | gcloud secrets create SERPER_API_KEY --data-file=-
```

## 3) Artifact Registry repo

```bash
gcloud artifacts repositories create $AR_REPO_NAME \
  --repository-format=docker \
  --location=$REGION
```

## 4) Build container (model baked into image)

Create files:

* `Dockerfile` (base: `vllm/vllm-openai:v0.11.0`, downloads `Qwen/Qwen3-4B-Instruct-2507` into `/model-cache`)
* `app/entrypoint.sh` (starts vLLM on 127.0.0.1:8000 + FastAPI gateway on 0.0.0.0:8080)
* `app/main.py` (endpoints: `/healthz`, `/readyz`, `POST /agent`, `POST /v1/chat/completions`)
* `cloudbuild.yaml` (uses HF_TOKEN as build secret)

Build:

```bash
gcloud builds submit --config=cloudbuild.yaml --substitutions=_LOCATION=$REGION
```

Set image var:

```bash
export IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$AR_REPO_NAME/$IMAGE_NAME:latest"
```

## 5) Deploy to Cloud Run (YOUR exact command)

```bash
gcloud beta run deploy "$SERVICE_NAME" \
  --image="$IMAGE" \
  --service-account="$RUN_SA_EMAIL" \
  --cpu=8 \
  --memory="32Gi" \
  --gpu=1 \
  --gpu-type="nvidia-l4" \
  --region="$REGION" \
  --port=8080 \
  --concurrency=1 \
  --max-instances=1 \
  --timeout=3600 \
  --no-cpu-throttling \
  --no-gpu-zonal-redundancy \
  --set-secrets=MAPS_API_KEY=MAPS_API_KEY:latest \
  --set-secrets=SERPER_API_KEY=SERPER_API_KEY:latest \
  --allow-unauthenticated \
  --startup-probe "httpGet.path=/readyz,httpGet.port=8080,initialDelaySeconds=240,failureThreshold=10,timeoutSeconds=30,periodSeconds=60"
```

## 6) Test

Get URL:

```bash
SERVICE_URL="$(gcloud run services describe $SERVICE_NAME --region $REGION --format='value(status.url)')"
echo "$SERVICE_URL"
```

Health:

```bash
curl "$SERVICE_URL/healthz"
curl "$SERVICE_URL/readyz"
```

Agent (IMPORTANT: POST, not GET):

```bash
curl -X POST "$SERVICE_URL/agent" \
  -H "Content-Type: application/json" \
  -d '{"input":"Find 3 ramen places near Times Square with Google Maps links."}'
```

OpenAI-style:

```bash
curl -X POST "$SERVICE_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model":"Qwen3-4B-Instruct-2507",
    "messages":[{"role":"user","content":"hello"}]
  }'
```

