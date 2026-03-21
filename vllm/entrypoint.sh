#!/usr/bin/env bash
set -euo pipefail

export PORT="${PORT:-8080}"
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"

MODEL_PATH="${VLLM_MODEL_PATH:-/model-cache/Qwen3-4B-Instruct-2507}"
SERVED_MODEL_NAME="${VLLM_SERVED_MODEL_NAME:-${VLLM_MODEL:-Qwen/Qwen3-4B-Instruct-2507}}"
TOOL_CALL_PARSER="${VLLM_TOOL_CALL_PARSER:-hermes}"

exec python3 -m vllm.entrypoints.openai.api_server \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --model "${MODEL_PATH}" \
  --served-model-name "${SERVED_MODEL_NAME}" \
  --gpu-memory-utilization "${VLLM_GPU_MEMORY_UTILIZATION:-0.70}" \
  --max-model-len "${VLLM_MAX_MODEL_LEN:-4096}" \
  --max-num-seqs "${VLLM_MAX_NUM_SEQS:-4}" \
  --enforce-eager \
  --enable-auto-tool-choice \
  --tool-call-parser "${TOOL_CALL_PARSER}"
