# vLLM - FastAPI Tool-Calling Service

This folder is the canonical orchestration surface for LLM operations. It includes:

- `planning.py`: planning orchestration used by backend routes (`/generate-plans`, `/refine`)
- `app/main.py`: optional standalone FastAPI tool-calling service (`/agent`, `/agent/stream`, `/v1/chat/completions`)
- vLLM health/readiness support (`/healthz`, `/readyz`)

## Structure

```text
.
├── planning.py           # Canonical planner orchestration for backend modules
├── app/
│   ├── main.py           # FastAPI app + tool-calling loop
│   ├── entrypoint.sh     # Starts vLLM + FastAPI
│   └── requirements.txt
├── Dockerfile.txt        # Container image build file
└── cloudbuild.yaml       # Google Cloud Build pipeline
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8080` | FastAPI server port |
| `VLLM_BASE_URL` | `http://127.0.0.1:8000/v1` | Base URL for vLLM OpenAI API |
| `MODEL_NAME` | `Qwen3-4B-Instruct-2507` | Served model name |
| `VLLM_API_KEY` | `EMPTY` | API key used by OpenAI client to call vLLM |
| `VLLM_HEALTH_TIMEOUT` | `3` | Timeout (seconds) for readiness ping |
| `VLLM_INFER_TIMEOUT` | `120` | Timeout (seconds) for inference calls |
| `MAPS_API_KEY` | empty | Enables `search_places` and `get_directions` tools |
| `VLLM_GPU_MEMORY_UTILIZATION` | `0.70` | vLLM GPU memory fraction |
| `VLLM_MAX_MODEL_LEN` | `4096` | Max sequence length |
| `VLLM_MAX_NUM_SEQS` | `4` | Max concurrent sequences |

## Build and Run (Docker)

The Docker build downloads `Qwen/Qwen3-4B-Instruct-2507` from Hugging Face using `HF_TOKEN`.

```bash
docker buildx build \
  -f Dockerfile.txt \
  --secret id=HF_TOKEN,env=HF_TOKEN \
  -t qwen3-vllm-tools:latest \
  .
```

```bash
docker run --rm -p 8080:8080 \
  -e MAPS_API_KEY="${MAPS_API_KEY}" \
  qwen3-vllm-tools:latest
```

## API Quick Start

Health:

```bash
curl http://localhost:8080/healthz
curl http://localhost:8080/readyz
```

Agent:

```bash
curl -X POST http://localhost:8080/agent \
  -H "Content-Type: application/json" \
  -d '{"input":"Find top coffee shops near Times Square"}'
```

OpenAI-compatible chat:

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen3-4B-Instruct-2507",
    "messages": [{"role":"user","content":"What is happening in AI this week?"}]
  }'
```

## Cloud Build

`cloudbuild.yaml` builds and pushes the image to Artifact Registry using substitutions:

- `_LOCATION`
- `_REPO` (default: `qwen3-vllm-repo`)
- `_NAME` (default: `qwen3-4b-2507-vllm-tools`)

Image tag format:

```text
${_LOCATION}-docker.pkg.dev/${PROJECT_ID}/${_REPO}/${_NAME}:latest
```
