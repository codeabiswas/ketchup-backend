# Ketchup Backend - Technical Architecture

## 1. System Overview

Ketchup is a Python backend for group-event planning plus a DAG-based data pipeline.
The repository combines:
- FastAPI application APIs for users/groups/plans/feedback flows
- Planner orchestration with OpenAI-compatible tool calling
- Data pipeline orchestration with Airflow (`daily_etl_pipeline`, `ketchup_comprehensive_pipeline`)
- Reproducible batch workflow with DVC (`dvc.yaml`)

The current architecture is optimized for local reproducibility with Docker Compose and supports Firestore emulator + Redis + Airflow metadata Postgres.

---

## 2. Runtime Architecture (Current)

```text
Client / Frontend
      |
      v
FastAPI (api/main.py)
  ├─ Route layer (api/routes/*)
  ├─ Service layer (services/*)
  ├─ Planner lifecycle (agents/planning.py)
  └─ Async DB lifecycle (database.connection)
      |
      +---- PostgreSQL (app data via asyncpg)
      +---- Redis (cache for API clients)
      +---- Firestore (or emulator in local)

Airflow (webserver + scheduler + init)
  ├─ daily_etl_pipeline
  ├─ ketchup_comprehensive_pipeline
  └─ logs + task state in airflow-postgres

DVC (dvc.yaml)
  └─ script-driven reproducible data stages over data/raw|processed|reports|statistics
```

---

## 3. Technology Stack (As Implemented)

### Core Backend
- Python 3.11+
- FastAPI
- Pydantic v2 + pydantic-settings
- asyncpg

### Planner / AI
- OpenAI Python client (OpenAI-compatible API usage)
- httpx + tenacity for resilient calls

### Data Pipeline
- Apache Airflow 2.7.2 (`LocalExecutor` in local stack)
- Pandas / NumPy in pipeline modules
- DVC for stage orchestration + data artifact versioning

### Storage / Infra
- PostgreSQL (app DB + separate Airflow metadata DB)
- Firestore client (points to emulator in local via `FIRESTORE_EMULATOR_HOST`)
- Redis cache
- Docker Compose for local environment

---

## 4. Repository Architecture

```text
ketchup-backend/
├─ api/                      # FastAPI app and route registration
│  └─ routes/                # auth, users, groups, plans, availability, feedback
├─ services/                 # business logic by domain
├─ agents/                   # planning orchestration/tool calling
├─ config/                   # typed settings from env
├─ database/                 # db connection + firestore client + migrations
├─ pipelines/                # preprocessing/validation/monitoring + airflow DAGs
│  └─ airflow/dags/          # daily_etl_dag.py, comprehensive_etl_dag.py
├─ scripts/                  # DVC stage scripts
├─ tests/                    # test_pipeline_components.py
├─ data/                     # raw/processed/metrics/reports/statistics artifacts
├─ dvc.yaml                  # reproducible stage graph
├─ docker-compose.yml        # local runtime topology
├─ README.md
└─ ARCHITECTURE.md
```

---

## 5. API Layer Architecture

## 5.1 App Lifecycle (`api/main.py`)
- On startup:
  - Connect async DB (`db.connect()`)
  - Initialize planner client (`init_planner_client()`)
  - Start invite-expiry background task
- On shutdown:
  - Cancel expiry task
  - Close planner client
  - Disconnect async DB

## 5.2 Mounted Routers (Current)
- `POST /api/auth/google-signin`
- `GET /api/users/me`
- `PUT /api/users/me/preferences`
- `GET /api/users/me/availability`
- `PUT /api/users/me/availability`
- `POST /api/groups`
- `GET /api/groups`
- `GET /api/groups/{group_id}`
- `PUT /api/groups/{group_id}`
- `POST /api/groups/{group_id}/invite`
- `POST /api/groups/{group_id}/invite/accept`
- `POST /api/groups/{group_id}/invite/reject`
- `PUT /api/groups/{group_id}/preferences`
- `POST /api/groups/{group_id}/availability`
- `POST /api/groups/{group_id}/generate-plans`
- `GET /api/groups/{group_id}/plans/{round_id}`
- `POST /api/groups/{group_id}/plans/{round_id}/vote`
- `GET /api/groups/{group_id}/plans/{round_id}/results`
- `POST /api/groups/{group_id}/plans/{round_id}/refine`
- `POST /api/groups/{group_id}/plans/{round_id}/finalize`
- `POST /api/groups/{group_id}/events/{event_id}/feedback`
- `GET /api/groups/{group_id}/events/{event_id}/feedback`
- `GET /health`
- `GET /`

---

## 6. Data and Integration Architecture

## 6.1 Configuration (`config/settings.py`)
Typed env-driven settings cover:
- DB (`database_url`)
- Planner runtime (`vllm_base_url`, model, timeouts, fallback flags)
- External integrations (`google_maps_api_key`, `tavily_api_key`)
- CORS + SMTP + frontend URL
- Cache/retry controls (`redis_url`, TTL, timeout, retries, backoff)
- Firestore target (`gcp_project_id`, credentials path, database)

A cached singleton settings object is exposed via `get_settings()` and `settings`.

## 6.2 Firestore Client (`database/firestore_client.py`)
- Encapsulates Firestore CRUD and query operations
- Supports credentialed or default client initialization
- Uses singleton access via `get_firestore_client()`
- Includes `get_all_users(active_only=True)` used by DAG acquisition tasks

## 6.3 API Clients (`utils/api_clients.py`)
- Base cached client with Redis + requests retry adapter
- Google Calendar client and Google Maps client wrappers
- Graceful behavior when Redis cache is unavailable

---

## 7. Pipeline Architecture

## 7.1 Airflow DAGs

### A) `daily_etl_pipeline` (`pipelines/airflow/dags/daily_etl_dag.py`)
Flow:
1. `extract_calendar_data`
2. `extract_venue_data`
3. `normalize_and_validate`
4. `sync_to_bigquery`
5. `report_metrics`

Notes:
- Designed as a daily operational ETL path
- Includes task-level logging and retry behavior

### B) `ketchup_comprehensive_pipeline` (`pipelines/airflow/dags/comprehensive_etl_dag.py`)
High-level stages:
1. Data acquisition
2. Preprocessing
3. Validation
4. Anomaly detection
5. Bias checks
6. Statistics generation
7. Storage
8. Final report

Important implementation details:
- Parse-safe fallback classes for logger/monitor/profiler if monitoring imports fail
- Runtime gate for heavy extended bias branch via Airflow Variable:
  - `run_extended_bias_analysis` (default false)
- Includes bottleneck summaries in final pipeline report
- Added guards for empty datasets / missing columns in preprocessing
- Report/statistics file writes create missing directories and handle NumPy scalar serialization

## 7.2 Monitoring (`pipelines/monitoring.py`)
- `PipelineLogger` for structured task logs (JSON logger when available)
- `PipelineMonitor` for metric recording and summaries
- `PerformanceProfiler` for task durations and bottleneck extraction
- Optional `AnomalyAlert` integrations (Slack/email)

---

## 8. DVC Stage Architecture (`dvc.yaml`)

Current stage graph includes:
1. `acquire_data`
2. `acquire_user_feedback`
3. `preprocess_data`
4. `validate_data`
5. `detect_anomalies`
6. `detect_bias`
7. `generate_synthetic_eval_data`
8. `analyze_bias_slices`
9. `fairlearn_bias_analysis`
10. `generate_statistics`

Outputs/metrics are tracked under:
- `data/raw/`
- `data/processed/`
- `data/metrics/`
- `data/reports/`
- `data/statistics/`

---

## 9. Local Deployment Architecture (`docker-compose.yml`)

Services:
- `firestore-emulator`
- `redis`
- `postgres` (app DB)
- `airflow-postgres` (Airflow metadata)
- `airflow-init`
- `airflow-scheduler`
- `airflow-webserver`
- `backend`

Notable runtime wiring:
- Airflow services run with `PYTHONPATH=/opt/airflow`
- Airflow extras install includes compatibility pins for pydantic stack and planner deps
- Airflow + backend both use `FIRESTORE_EMULATOR_HOST=firestore-emulator:8080`
- Shared source mount enables DAGs/scripts to run current workspace code

---

## 10. Reliability and Error Handling

Current resilience patterns in codebase:
- Task-level `try/except` with explicit `AirflowException` for actionable retries/failures
- Fallback monitoring objects prevent DAG parse-time hard failures
- Local run hardening:
  - Firestore emulator dependency explicitly required in startup commands
  - Preprocess/stat/report tasks robust to empty inputs and serialization edge cases
- Database package import guard in `database/__init__.py` to reduce import-side breakage

---

## 11. Performance and Flow Optimization

Implemented optimization controls:
- Parallelizable acquisition branches in DAG flow
- Optional heavy bias branch gated by `run_extended_bias_analysis`
- Profiling and bottleneck extraction via `PerformanceProfiler.get_bottlenecks()`
- Airflow Gantt + task duration views are the primary operational bottleneck inspection tools

Useful query (Airflow metadata DB) for slow-task ranking:
```sql
select task_id,
       round(avg(extract(epoch from (end_date-start_date)))::numeric,2) as avg_s,
       count(*)
from task_instance
where dag_id='ketchup_comprehensive_pipeline'
  and state='success'
  and end_date is not null
group by task_id
order by avg_s desc;
```

---

## 12. Known Operational Notes

- If tasks fail with Firestore DNS errors (`firestore-emulator` not found), start/check emulator container first.
- Some historical failed runs may remain in Airflow metadata; validate current behavior using a fresh run ID.
- Extended bias tasks can be intentionally skipped when gate variable is disabled (expected behavior, not failure).

---

## 13. Summary

The current architecture is a layered FastAPI + Airflow + DVC system with:
- Clear separation of API, services, data access, and pipeline orchestration
- Reproducible local environment via Docker Compose
- Reproducible data workflow via DVC stages
- Practical runtime hardening for local reliability and assignment-focused evaluation criteria
