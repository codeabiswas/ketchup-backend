#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <project-id> <region> [repo] [image-name] [tag]"
  exit 1
fi

PROJECT_ID="$1"
REGION="$2"
REPO="${3:-ketchup-vllm-dev}"
IMAGE_NAME="${4:-qwen3-4b-2507-vllm}"
TAG="${5:-latest}"
GCLOUD_BIN="${GCLOUD_BIN:-gcloud}"
MODEL_REPO="${VLLM_MODEL_REPO:-Qwen/Qwen3-4B-Instruct-2507}"
MODEL_DIR="${VLLM_MODEL_DIR:-Qwen3-4B-Instruct-2507}"

"${GCLOUD_BIN}" builds submit \
  --project "${PROJECT_ID}" \
  --config vllm/cloudbuild.yaml \
  --substitutions "_IMAGE=${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${IMAGE_NAME}:${TAG},_MODEL_REPO=${MODEL_REPO},_MODEL_DIR=${MODEL_DIR}"
