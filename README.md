# Ketchup Backend

FastAPI backend plus data pipeline for planning, voting, and analytics feature materialization. For a deeper dive on the methodology this takes for the data pipeline, please refer to `data_pipeline.md`.

## What This Repo Owns

- API and business logic (`api/`, `services/`, `agents/`)
- Postgres schema and analytics tables (`database/migrations/`)
- Data pipeline stages, DVC graph, and Airflow DAGs (`scripts/`, `dvc.yaml`, `pipelines/`)

## Recommended Runtime (Docker + uv)

Use this repository's Compose stack to avoid maintaining multiple local Python environments.

1) Configure environment (Note: Do not worry about having keys for running Data Pipeline):

```bash
# Enter repository root
cd ketchup-backend

# Copy template environment file for local configuration
cp .env.example .env
```

2) Start API + Postgres:

```bash
# Build images and start API + Postgres services in foreground
docker compose up --build db api
```

To run the repo with the local standalone vLLM server added in this branch:

```bash
docker compose --profile llm up --build db vllm api
```

3) Start pipeline worker (separate terminal):

```bash
# Build (if needed) and start pipeline worker + DB in background
docker compose --profile pipeline up --build -d db pipeline
```

4) Run pipeline actions through the pipeline container:

```bash
# Re-run all DVC stages end-to-end (forces recomputation)
docker compose --profile pipeline exec pipeline uv run --no-project dvc repro -f

# Run pipeline unit/integration tests
docker compose --profile pipeline exec pipeline uv run --no-project pytest tests/test_pipeline_components.py -v

# Print DVC dependency graph
docker compose --profile pipeline exec pipeline uv run --no-project dvc dag

# Apply/upgrade Airflow metadata DB schema
docker compose --profile pipeline exec pipeline uv run --no-project airflow db migrate

# Trigger daily analytics DAG
docker compose --profile pipeline exec pipeline uv run --no-project airflow dags trigger daily_analytics_materialization # If this fails, rerun `dvc dag` and `airflow db migrate`

# Trigger comprehensive ETL + analytics DAG
docker compose --profile pipeline exec pipeline uv run --no-project airflow dags trigger ketchup_comprehensive_pipeline

# Create Airflow admin user for UI login (safe to rerun; may warn if user exists)
docker compose --profile pipeline exec pipeline uv run --no-project airflow users create \
    --username admin \
    --firstname Admin \
    --lastname User \
    --role Admin \
    --email admin@local \
    --password admin

# Start Airflow scheduler loop (keep this terminal open)
docker compose --profile pipeline exec pipeline uv run --no-project airflow scheduler

# Run Airflow webserver in another terminal and expose UI on localhost:8082
docker compose --profile pipeline run --rm -p 8082:8082 pipeline uv run --no-project airflow webserver --port 8082
```

Notes:

- API container uses Python 3.12 (`Dockerfile`).
- Pipeline container uses Python 3.11 for Airflow compatibility (`Dockerfile.pipeline`).
- Both images install dependencies with `uv`.
- Backend Compose DB is internal-only (no host port binding) to avoid clashes with `ketchup-local`.

## Environment Variables

Core:

- `DATABASE_URL`
- `DATABASE_URL_INTERNAL` (Compose internal DB URL; defaults to `postgresql://postgres:postgres@db:5432/appdb`)
- `FRONTEND_URL`
- `BACKEND_INTERNAL_API_KEY`

Planner endpoint:

- `VLLM_BASE_URL` (OpenAI-compatible `/v1` endpoint)
- `VLLM_BASE_URL_INTERNAL` (Compose internal LLM URL; defaults to `http://host.docker.internal:8080/v1`)
- `VLLM_MODEL`
- `VLLM_API_KEY`

Planner behavior:

- `PLANNER_NOVELTY_TARGET_GENERATE`
- `PLANNER_NOVELTY_TARGET_REFINE`
- `PLANNER_FALLBACK_ENABLED`

Standalone vLLM service:

- `HF_TOKEN`
- `VLLM_MODEL_REPO`
- `VLLM_MODEL_DIR`
- `VLLM_MODEL_PATH`
- `VLLM_GPU_MEMORY_UTILIZATION`
- `VLLM_MAX_MODEL_LEN`
- `VLLM_MAX_NUM_SEQS`
- `VLLM_TOOL_CALL_PARSER`

Tooling:

- `GOOGLE_MAPS_API_KEY` for Maps tools
- `TAVILY_API_KEY` for web search fallback

## Planner Runtime Contract

- Planner calls an OpenAI-compatible chat completions API.
- No llama.cpp-specific fields are sent.
- Tool-calling is used when server/model supports it.
- If tool output is invalid/empty, deterministic grounded fallback is used.

For vLLM auto tool-calling, run vLLM with:

- `--enable-auto-tool-choice`
- `--tool-call-parser <model-compatible-parser>`

This branch adds a dedicated standalone vLLM server surface in `vllm/` for that purpose. The backend still remains the planner orchestrator; the vLLM service is only the raw model endpoint.

## Model Bias Scripts

For Section 2.4 and Section 2.5 work, use:

- `python scripts/run_model_bias_synthetic_eval.py`
- `python scripts/check_model_bias_slices.py`
- `python scripts/check_model_bias_fairlearn.py`

These write generated outputs under `data/reports/` and document slice-based bias checks for the planning model.

## Tool-Calling Benchmark

For a detached 25-example synthetic tool-calling benchmark against a running vLLM endpoint, use:

- `python scripts/evaluate_tool_calling_bfcl.py --model <served-model-name>`
- `python scripts/evaluate_tool_calling_bfcl.py --model <served-model-name> --wandb-project <project>`

This uses a local synthetic dataset in `data/benchmarks/synthetic_group_outings_tool_calling.json` with diverse group-outing requests, mock Google Maps-style tools, web-search cases, and no-tool abstain cases. Decision and tool-name checks are exact, but argument quality is scored semantically by an LLM judge using the served model. The script writes a JSON summary under `data/reports/` and can log per-example running metrics plus final results to Weights & Biases.

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| `dvc` fails with `_DIR_MARK` import error | `pathspec` drift | run inside pipeline container (pinned deps) |
| Airflow import errors (`flask_session` / `connexion`) | package drift in host venv | run Airflow via pipeline container |
| Planner tool loop disabled by server | vLLM missing tool-call flags | add `--enable-auto-tool-choice --tool-call-parser ...` |

## Related Docs

- `data_pipeline.md`
- `gcp.md`
- `agents/README.md`
- `vllm/README.md`
- `pipelines/model_bias.md`
