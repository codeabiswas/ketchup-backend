# Ketchup Backend

FastAPI backend plus data/model pipeline for planning, voting, and analytics feature materialization.

- For a deeper dive on the data pipeline methodology, see `data_pipeline.md`.
- For a deeper dive on the model pipeline methodology, see `model-pipeline.md`.
- For infrastructure/cloud details, see `gcp.md`.

## What This Repo Owns

- API and business logic (`api/`, `services/`, `agents/`)
- Postgres schema and analytics tables (`database/migrations/`)
- Data pipeline stages, DVC graph, and Airflow DAGs (`scripts/`, `dvc.yaml`, `pipelines/`)
- Standalone vLLM serving surface (`vllm/`)
- Cloud Run + Cloud SQL infrastructure as Terraform (`terraform/`)
- CI/CD workflows (`.github/workflows/`)

---

## Setup

### Prerequisites

- Docker + Docker Compose
- Python 3.11/3.12 only needed if you want to run things outside containers
- A `.env` file at the repo root (see below). `.env.example` is not tracked — create `.env` directly using the template in the next section.

### 1) Create `.env`

Create `ketchup-backend/.env` with the following (fill in secrets as needed — keys are only required for the planner tool-calling path, not for running the data pipeline):

```bash
# Postgres
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/appdb
DATABASE_URL_INTERNAL=postgresql://postgres:postgres@db:5432/appdb

# vLLM (planner LLM endpoint, OpenAI-compatible)
VLLM_BASE_URL=http://localhost:8080/v1
VLLM_BASE_URL_INTERNAL=http://host.docker.internal:8080/v1
VLLM_MODEL=Qwen/Qwen3-4B-Instruct-2507
VLLM_API_KEY=EMPTY

# Planner behaviour
PLANNER_NOVELTY_TARGET_GENERATE=0.7
PLANNER_NOVELTY_TARGET_REFINE=0.35
PLANNER_FALLBACK_ENABLED=false

# Auth / tooling
BACKEND_INTERNAL_API_KEY=change-me-in-production
GOOGLE_MAPS_API_KEY=
TAVILY_API_KEY=
FRONTEND_URL=http://localhost:3001
```

### 2) Start API + Postgres

```bash
docker compose up --build db api
```

To also run the standalone vLLM server locally (requires GPU + `HF_TOKEN`):

```bash
docker compose --profile llm up --build db vllm api
```

API: <http://localhost:8000>  •  vLLM: <http://localhost:8080>

### 3) Run the data pipeline worker (separate terminal)

```bash
docker compose --profile pipeline up --build -d db pipeline
```

Common pipeline actions through the pipeline container:

```bash
# Re-run all DVC stages end-to-end
docker compose --profile pipeline exec pipeline uv run --no-project dvc repro -f

# Pipeline unit/integration tests
docker compose --profile pipeline exec pipeline uv run --no-project pytest tests/test_pipeline_components.py -v

# Print DVC dependency graph
docker compose --profile pipeline exec pipeline uv run --no-project dvc dag

# Apply/upgrade Airflow metadata DB schema
docker compose --profile pipeline exec pipeline uv run --no-project airflow db migrate

# Trigger analytics DAGs (run `dvc dag` + `airflow db migrate` first if these fail)
docker compose --profile pipeline exec pipeline uv run --no-project airflow dags trigger daily_analytics_materialization
docker compose --profile pipeline exec pipeline uv run --no-project airflow dags trigger ketchup_comprehensive_pipeline

# Create Airflow admin user (safe to rerun)
docker compose --profile pipeline exec pipeline uv run --no-project airflow users create \
    --username admin --firstname Admin --lastname User --role Admin \
    --email admin@local --password admin

# Airflow scheduler (keep terminal open)
docker compose --profile pipeline exec pipeline uv run --no-project airflow scheduler

# Airflow webserver on localhost:8082
docker compose --profile pipeline run --rm -p 8082:8082 pipeline uv run --no-project airflow webserver --port 8082
```

### 4) Run tests locally (no containers)

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

Markers defined in `pytest.ini`: `unit`, `integration`, `slow`, `smoke`.

### Notes

- API container uses Python 3.12 (`Dockerfile`); pipeline container uses Python 3.11 for Airflow compatibility (`Dockerfile.pipeline`). Both install deps via `uv`.
- The Compose Postgres is internal-only (no host port binding) to avoid clashes with `ketchup-local`.

---

## Environment Variables

Core:

- `DATABASE_URL`, `DATABASE_URL_INTERNAL` (Compose internal default: `postgresql://postgres:postgres@db:5432/appdb`)
- `FRONTEND_URL`
- `BACKEND_INTERNAL_API_KEY`

Planner endpoint:

- `VLLM_BASE_URL` — OpenAI-compatible `/v1` endpoint
- `VLLM_BASE_URL_INTERNAL` — Compose internal default: `http://host.docker.internal:8080/v1`
- `VLLM_MODEL`, `VLLM_API_KEY`

Planner behaviour:

- `PLANNER_NOVELTY_TARGET_GENERATE`, `PLANNER_NOVELTY_TARGET_REFINE`, `PLANNER_FALLBACK_ENABLED`

Standalone vLLM service:

- `HF_TOKEN`, `VLLM_MODEL_REPO`, `VLLM_MODEL_DIR`, `VLLM_MODEL_PATH`
- `VLLM_GPU_MEMORY_UTILIZATION`, `VLLM_MAX_MODEL_LEN`, `VLLM_MAX_NUM_SEQS`, `VLLM_TOOL_CALL_PARSER`

Tooling:

- `GOOGLE_MAPS_API_KEY` for Maps tools
- `TAVILY_API_KEY` for web search fallback

---

## Planner Runtime Contract

- Planner calls an OpenAI-compatible chat completions API.
- No llama.cpp-specific fields are sent.
- Tool-calling is used when server/model supports it.
- If tool output is invalid/empty, deterministic grounded fallback is used.

For vLLM auto tool-calling, run vLLM with:

- `--enable-auto-tool-choice`
- `--tool-call-parser <model-compatible-parser>`

The standalone vLLM server in `vllm/` sets these in its entrypoint. The backend still owns planner orchestration; the vLLM service is only the raw model endpoint.

---

## Model Bias & Tool-Calling Scripts

Model bias (Sections 2.4 & 2.5):

- `python scripts/run_model_bias_synthetic_eval.py`
- `python scripts/check_model_bias_slices.py`
- `python scripts/check_model_bias_fairlearn.py`

Outputs land under `data/reports/`.

Synthetic tool-calling benchmark (25 examples against a running vLLM endpoint):

```bash
python scripts/evaluate_tool_calling_bfcl.py --model <served-model-name>
python scripts/evaluate_tool_calling_bfcl.py --model <served-model-name> --wandb-project <project>
```

Uses `data/benchmarks/synthetic_group_outings_tool_calling.json`. Decision/tool-name checks are exact; argument quality is scored by an LLM judge using the served model. Writes a JSON summary under `data/reports/` and can log per-example running metrics + final results to Weights & Biases.

---

## GitHub Workflows

Three workflows live under `.github/workflows/`. A shared composite action `.github/actions/notify-failure` emails `ALERT_EMAIL_TO` on any failure (used by all three).

### `deploy-backend.yml` — Deploy Backend to GCP

**Triggers:** push to `main` or `staging` (skips doc-only / model-pipeline-only changes), or manual `workflow_dispatch` with an optional `environment` override (`dev` / `prod`).

**Environment resolution:** `main` → `prod`, `staging` → `dev`, dispatch input wins when set.

**Jobs:**

1. `test` — sets up Python, installs `requirements.txt` + `requirements-dev.txt`, runs `pytest`.
2. `build-and-deploy` (needs `test`) —
   - Authenticates to GCP via `GCP_SA_KEY` service account JSON.
   - Ensures an Artifact Registry repo `ketchup-backend-${env}` exists.
   - Builds and pushes the backend image tagged with both `:${sha}` and `:latest`.
   - Runs Terraform against `terraform/` with a generated `terraform.tfvars` (project, region, env, image, frontend URL, vLLM URL/model, min/max instances, DB tier, SMTP settings). Remote state lives at `gs://${GCS_TF_STATE_BUCKET}/terraform/state/${env}`.
   - Imports any pre-existing Secret Manager secrets (`DATABASE_URL_${env}`, `GOOGLE_MAPS_API_KEY_${env}`, `TAVILY_API_KEY_${env}`, `VLLM_API_KEY_${env}`, `BACKEND_INTERNAL_API_KEY_${env}`, `HF_TOKEN_${env}`, `SMTP_PASSWORD_${env}`) so `terraform apply` doesn't 409.
   - Adds new secret versions from repo secrets.
   - Writes deployment summary (env, branch, image, backend URL, health-check command) to the job summary.

**Required repo variables:** `GCP_PROJECT_ID`, `GCP_REGION`, `GCS_TF_STATE_BUCKET`, `FRONTEND_URL`, `VLLM_BASE_URL`, `VLLM_MODEL`, `BACKEND_MIN_INSTANCES`, `BACKEND_MAX_INSTANCES`, `DB_INSTANCE_TIER`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_FROM_EMAIL`, `ALERT_EMAIL_TO`.

**Required repo secrets:** `GCP_SA_KEY`, `GOOGLE_MAPS_API_KEY`, `TAVILY_API_KEY`, `VLLM_API_KEY`, `BACKEND_INTERNAL_API_KEY`, `HF_TOKEN`, `SMTP_PASSWORD`.

### `deploy-vllm.yml` — Deploy vLLM to GCP

**Triggers:** push to `main`/`staging` touching `vllm/**`, `scripts/push_vllm_image.sh`, `scripts/deploy_vllm_cloud_run.sh`, or this workflow file. Also `workflow_dispatch` with these inputs:

- `service_name` — override `VLLM_SERVICE_NAME` variable
- `allow_public` — allow unauthenticated invocations (default `true`)
- `skip_build` — skip Cloud Build and redeploy the existing image (default `true`, the fast path)
- `image_tag` — which tag to redeploy when `skip_build=true` (default `latest`)
- `auto_deploy_backend` — after vLLM deploys, update the `VLLM_BASE_URL` repo variable and trigger `deploy-backend.yml` (default `true`)
- `backend_ref` — branch to run the backend deploy on (`main` = prod, `staging` = dev)

**Flow:**

1. Validates required variables/secrets are present.
2. Authenticates using the dedicated vLLM service account (`VLLM_GCP_SA_KEY`) and enables Secret Manager.
3. **Build path (`skip_build=false`):** provisions `HF_TOKEN` in Secret Manager, grants Cloud Build access to it, then runs `scripts/deploy_vllm_cloud_run.sh` which builds via Cloud Build and deploys to Cloud Run GPU.
4. **Deploy-only path (`skip_build=true`, default):** reuses the image already in Artifact Registry and runs `gcloud run deploy` directly with full Cloud Run GPU config (L4 GPU, 8 CPU / 32Gi default, concurrency 1, 900s timeout).
5. Captures the service URL, polls `/health` for up to 5 minutes, and runs a concurrent 5-request smoke test against `/v1/chat/completions`.
6. If `auto_deploy_backend=true`, updates the repo variable `VLLM_BASE_URL` and runs `gh workflow run deploy-backend.yml --ref ${backend_ref}` so the backend picks up the new URL. Requires `GH_DISPATCH_TOKEN` (PAT with `repo` + `workflow` scopes).

**Required repo variables:** `VLLM_GCP_PROJECT_ID`, `VLLM_GCP_REGION`, `VLLM_SERVICE_NAME`, `VLLM_REPO_NAME`, `VLLM_IMAGE_NAME`, `VLLM_GPU_TYPE`, `VLLM_CPU`, `VLLM_MEMORY`, `VLLM_MIN_INSTANCES`, `VLLM_MAX_INSTANCES`, `VLLM_MODEL_REPO`, `VLLM_MODEL_DIR`, `VLLM_MAX_MODEL_LEN`, `VLLM_MAX_NUM_SEQS`, `VLLM_GPU_MEMORY_UTILIZATION`, `VLLM_TOOL_CALL_PARSER`.

**Required repo secrets:** `VLLM_GCP_SA_KEY`, `HF_TOKEN`, `GH_DISPATCH_TOKEN` (only when `auto_deploy_backend=true`).

### `model-pipeline.yml` — Model Pipeline

**Triggers:** push to `main` that touches the bias / tool-calling scripts, `pipelines/bias_detection.py`, `data/benchmarks/**`, or `dvc.yaml`. Also `workflow_dispatch`.

**Steps:**

1. Python 3.11 + `pip install -r requirements-pipeline.txt dvc`.
2. Validates `VLLM_BASE_URL` is set (pointing at the Cloud Run service **root**, without `/v1` — the eval scripts append `/v1/...` internally).
3. Runs the DVC bias stages: `dvc repro model_bias_eval model_bias_slices model_bias_fairlearn`.
4. Runs the synthetic tool-calling benchmark against `VLLM_BASE_URL` with `VLLM_MODEL`.
5. Uploads reports as the `model-evaluation-reports` artifact:
   - `data/reports/model_bias_results.csv`
   - `data/reports/model_bias_slicing_report.md`
   - `data/reports/tool_calling_group_outings_synthetic_25.json`

### Typical Deployment Flow

1. Push to `staging` → `deploy-backend.yml` tests + deploys backend to `dev`.
2. Merge/push to `main` → same, but to `prod`.
3. Change anything under `vllm/` or the vLLM scripts → `deploy-vllm.yml` redeploys Cloud Run GPU (deploy-only fast path by default) and, because `auto_deploy_backend` defaults to `true` on manual dispatch, can chain into a backend redeploy with the fresh `VLLM_BASE_URL`.
4. For a full image rebuild of vLLM, manually dispatch `deploy-vllm.yml` with `skip_build` unchecked.
5. Manually dispatch `model-pipeline.yml` (or push changes to the bias/tool-calling scripts on `main`) to regenerate evaluation reports against the deployed vLLM.

### Manual vLLM Deploy (local machine)

If you need to deploy vLLM to Cloud Run outside CI:

```bash
GCLOUD_BIN="$HOME/google-cloud-sdk/bin/gcloud" \
./scripts/deploy_vllm_cloud_run.sh YOUR_PROJECT_ID us-east1
```

Afterwards, set these repo variables so `model-pipeline.yml` can reach the service:

- `VLLM_BASE_URL=https://<cloud-run-service>` (service root — **no** trailing `/v1`)
- `VLLM_MODEL=Qwen/Qwen3-4B-Instruct-2507`

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| `dvc` fails with `_DIR_MARK` import error | `pathspec` drift | run inside pipeline container (pinned deps) |
| Airflow import errors (`flask_session` / `connexion`) | package drift in host venv | run Airflow via pipeline container |
| Planner tool loop disabled by server | vLLM missing tool-call flags | add `--enable-auto-tool-choice --tool-call-parser ...` |
| `The model \` Qwen/... \` does not exist` from vLLM | leading/trailing whitespace in `VLLM_MODEL` GitHub variable | re-save the variable without extra spaces |
| DVC fails to parse `VLLM_BASE_URL:-...` | shell-style default expansion placed directly in `dvc.yaml` | let the script read env vars itself instead of embedding shell defaults in the DVC command |
| Workflow reaches Cloud Run manually but gets early `404`/timeouts in Actions | Cloud Run GPU cold start | rerun after warm-up or rely on the eval scripts' built-in retries |
| `deploy-vllm.yml` auto-deploy step errors on `GH_DISPATCH_TOKEN` | secret missing | add a PAT with `repo` + `workflow` scope, or dispatch with `auto_deploy_backend=false` |
| Terraform apply fails with `409 already exists` on a secret | secret was created manually outside TF state | the workflow imports known secrets automatically; for a new one, add it to the `SECRETS` map in `deploy-backend.yml` |

---

## Related Docs

- `model-pipeline.md`
- `data_pipeline.md`
- `gcp.md`
- `agents/README.md`
- `vllm/README.md`
- `pipelines/model_bias.md`
