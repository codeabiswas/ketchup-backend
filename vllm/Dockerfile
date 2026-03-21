# syntax=docker/dockerfile:1.4
FROM vllm/vllm-openai:v0.11.0

ENV HF_HOME=/model-cache \
    TRANSFORMERS_CACHE=/model-cache \
    HF_HUB_DISABLE_TELEMETRY=1

ARG HF_TOKEN=""
ARG VLLM_MODEL_REPO="Qwen/Qwen3-4B-Instruct-2507"
ARG VLLM_MODEL_DIR="Qwen3-4B-Instruct-2507"

RUN --mount=type=secret,id=HF_TOKEN \
    HF_TOKEN="$HF_TOKEN" VLLM_MODEL_REPO="$VLLM_MODEL_REPO" VLLM_MODEL_DIR="$VLLM_MODEL_DIR" python3 - <<'PY'
import inspect
import os
from pathlib import Path

from huggingface_hub import snapshot_download

secret_path = Path("/run/secrets/HF_TOKEN")
token = secret_path.read_text().strip() if secret_path.exists() else os.environ.get("HF_TOKEN", "").strip()
if not token:
    raise SystemExit("HF_TOKEN build arg or BuildKit secret is required to download the model.")

repo_id = os.environ["VLLM_MODEL_REPO"]
model_dir = os.environ["VLLM_MODEL_DIR"]

kwargs = {
    "repo_id": repo_id,
    "local_dir": f"/model-cache/{model_dir}",
    "token": token,
}

sig = inspect.signature(snapshot_download)
if "local_dir_use_symlinks" in sig.parameters:
    kwargs["local_dir_use_symlinks"] = False

snapshot_download(**kwargs)
PY

ENV HF_HUB_OFFLINE=1 \
    VLLM_MODEL_PATH=/model-cache/${VLLM_MODEL_DIR}

WORKDIR /srv/vllm
COPY vllm/entrypoint.sh /srv/vllm/entrypoint.sh
RUN chmod +x /srv/vllm/entrypoint.sh

ENTRYPOINT ["/srv/vllm/entrypoint.sh"]
