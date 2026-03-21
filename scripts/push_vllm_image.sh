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

gcloud builds submit \
  --project "${PROJECT_ID}" \
  --config vllm/cloudbuild.yaml \
  --substitutions "_LOCATION=${REGION},_REPO=${REPO},_NAME=${IMAGE_NAME},_IMAGE=${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${IMAGE_NAME}:${TAG}"
