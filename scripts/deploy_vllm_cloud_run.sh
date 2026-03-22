#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <project-id> <region> [service] [repo] [image-name] [tag]"
  exit 1
fi

PROJECT_ID="$1"
REGION="$2"
SERVICE="${3:-ketchup-vllm}"
REPO="${4:-ketchup-vllm-dev}"
IMAGE_NAME="${5:-qwen3-4b-2507-vllm}"
TAG="${6:-latest}"
GCLOUD_BIN="${GCLOUD_BIN:-gcloud}"

GPU_TYPE="${GPU_TYPE:-nvidia-l4}"
GPU_COUNT="${GPU_COUNT:-1}"
CPU="${CPU:-8}"
MEMORY="${MEMORY:-32Gi}"
MIN_INSTANCES="${MIN_INSTANCES:-0}"
MAX_INSTANCES="${MAX_INSTANCES:-1}"
TIMEOUT="${TIMEOUT:-900}"
CONCURRENCY="${CONCURRENCY:-1}"
ALLOW_PUBLIC="${ALLOW_PUBLIC:-true}"
GPU_ZONAL_REDUNDANCY_FLAG="${GPU_ZONAL_REDUNDANCY_FLAG:---no-gpu-zonal-redundancy}"

VLLM_MODEL="${VLLM_MODEL:-Qwen/Qwen3-4B-Instruct-2507}"
VLLM_MODEL_DIR="${VLLM_MODEL_DIR:-Qwen3-4B-Instruct-2507}"
VLLM_GPU_MEMORY_UTILIZATION="${VLLM_GPU_MEMORY_UTILIZATION:-0.70}"
VLLM_MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:-4096}"
VLLM_MAX_NUM_SEQS="${VLLM_MAX_NUM_SEQS:-4}"
VLLM_TOOL_CALL_PARSER="${VLLM_TOOL_CALL_PARSER:-hermes}"

IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${IMAGE_NAME}:${TAG}"

echo "[1/4] Enabling required APIs"
"${GCLOUD_BIN}" services enable \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  --project "${PROJECT_ID}"

echo "[2/4] Ensuring Artifact Registry repository exists"
if ! "${GCLOUD_BIN}" artifacts repositories describe "${REPO}" \
  --location "${REGION}" \
  --project "${PROJECT_ID}" >/dev/null 2>&1; then
  "${GCLOUD_BIN}" artifacts repositories create "${REPO}" \
    --repository-format docker \
    --location "${REGION}" \
    --project "${PROJECT_ID}"
fi

echo "[3/4] Building and pushing vLLM image"
GCLOUD_BIN="${GCLOUD_BIN}" \
  "$(dirname "$0")/push_vllm_image.sh" "${PROJECT_ID}" "${REGION}" "${REPO}" "${IMAGE_NAME}" "${TAG}"

echo "[4/4] Deploying Cloud Run service ${SERVICE}"
deploy_args=(
  run deploy "${SERVICE}"
  --project "${PROJECT_ID}"
  --region "${REGION}"
  --platform managed
  --image "${IMAGE_URI}"
  --port 8080
  --cpu "${CPU}"
  --memory "${MEMORY}"
  --gpu "${GPU_COUNT}"
  --gpu-type "${GPU_TYPE}"
  --no-cpu-throttling
  --min-instances "${MIN_INSTANCES}"
  --max-instances "${MAX_INSTANCES}"
  --concurrency "${CONCURRENCY}"
  --timeout "${TIMEOUT}"
  --set-env-vars "VLLM_MODEL=${VLLM_MODEL},VLLM_MODEL_PATH=/model-cache/${VLLM_MODEL_DIR},VLLM_GPU_MEMORY_UTILIZATION=${VLLM_GPU_MEMORY_UTILIZATION},VLLM_MAX_MODEL_LEN=${VLLM_MAX_MODEL_LEN},VLLM_MAX_NUM_SEQS=${VLLM_MAX_NUM_SEQS},VLLM_TOOL_CALL_PARSER=${VLLM_TOOL_CALL_PARSER}"
)

if [[ "${GPU_ZONAL_REDUNDANCY_FLAG}" != "none" ]]; then
  deploy_args+=("${GPU_ZONAL_REDUNDANCY_FLAG}")
fi

if [[ "${ALLOW_PUBLIC}" == "true" ]]; then
  deploy_args+=(--no-invoker-iam-check)
fi

"${GCLOUD_BIN}" "${deploy_args[@]}"

SERVICE_URL="$("${GCLOUD_BIN}" run services describe "${SERVICE}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --format='value(status.url)')"

echo
echo "Cloud Run service deployed:"
echo "  SERVICE_URL=${SERVICE_URL}"
echo "  HEALTH_URL=${SERVICE_URL}/health"
echo "  MODELS_URL=${SERVICE_URL}/v1/models"
