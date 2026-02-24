# Ketchup Backend

FastAPI backend for groups, planning rounds, voting, invites, availability, and feedback.

This repository follows that requirement by keeping:
- A concise project-level README (this file)
- A dedicated pipeline submission document in `data_pipeline.md`
- A synchronized architecture reference in `ARCHITECTURE.md`

## Quick Links

- Data pipeline submission: `data_pipeline.md`
- Technical architecture: `ARCHITECTURE.md`
- Airflow DAGs: `pipelines/airflow/dags/daily_etl_dag.py`, `pipelines/airflow/dags/comprehensive_etl_dag.py`
- DVC stage graph: `dvc.yaml`
- Tests: `tests/test_pipeline_components.py`

## Folder Structure

```text
ketchup-backend/
├─ api/
├─ agents/
├─ config/
├─ data/
│  ├─ raw/
│  ├─ processed/
│  ├─ metrics/
│  ├─ reports/
│  └─ statistics/
├─ database/
├─ pipelines/
│  ├─ airflow/
│  │  └─ dags/
├─ scripts/
├─ services/
├─ tests/
├─ logs/
├─ dvc.yaml
├─ docker-compose.yml
├─ requirements.txt
├─ README.md
└─ data_pipeline.md
```

## Setup

```bash
uv venv
# Windows
.venv\Scripts\activate
uv sync --all-groups
```

## Run (Local)

```bash
docker compose up -d firestore-emulator redis airflow-postgres airflow-init airflow-scheduler airflow-webserver
docker compose exec airflow-webserver airflow dags list
docker compose exec airflow-webserver airflow dags trigger ketchup_comprehensive_pipeline
```

## Reproducibility

```bash
dvc repro
pytest tests/test_pipeline_components.py -v
```
