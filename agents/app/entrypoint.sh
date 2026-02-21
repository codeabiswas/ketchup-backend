#!/usr/bin/env bash
set -euo pipefail

export PORT="${PORT:-8080}"
export VLLM_PORT="8000"
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"

python3 -m vllm.entrypoints.openai.api_server \
  --host 127.0.0.1 \
  --port "${VLLM_PORT}" \
  --model "/model-cache/Qwen3-4B-Instruct-2507" \
  --served-model-name "Qwen3-4B-Instruct-2507" \
  --gpu-memory-utilization "${VLLM_GPU_MEMORY_UTILIZATION:-0.70}" \
  --max-model-len "${VLLM_MAX_MODEL_LEN:-4096}" \
  --max-num-seqs "${VLLM_MAX_NUM_SEQS:-4}" \
  --enforce-eager \
  --enable-auto-tool-choice \
  --tool-call-parser hermes \
  > /proc/1/fd/1 2>/proc/1/fd/2 &

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"
