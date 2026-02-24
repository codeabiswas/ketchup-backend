# Data Pipeline

This folder contains optional ETL and quality workflows. It is separate from the core
FastAPI runtime so backend API development is not blocked by pipeline dependencies.

## Components

- `preprocessing.py`: cleaners, aggregators, feature engineering helpers
- `validation.py`: schema/range/anomaly checks and statistics export
- `bias_detection.py`: demographic slicing and fairness metrics
- `monitoring.py`: structured logging, alerts, profiling helpers
- `airflow/dags/daily_etl_dag.py`: daily extraction/normalization/metrics
- `airflow/dags/comprehensive_etl_dag.py`: extended quality checks + optional bias analysis
- `scripts/*.py`: script-driven DVC stages
- `dvc.yaml`: reproducible stage graph

## Dependency model

Core backend dependencies live in `requirements.txt`.
Pipeline dependencies are optional and should be installed separately for ETL runs:

```bash
pip install pandas numpy scipy requests redis dvc fairlearn \
  google-cloud-firestore python-json-logger
pip install apache-airflow==2.7.2 apache-airflow-providers-google==10.10.0
```

## DVC flow (optional)

```bash
dvc repro
dvc dag
```

`dvc repro` generates:
- `data/raw/*`, `data/processed/*`, `data/metrics/*`, `data/reports/*`, `data/statistics/*`
- `dvc.lock`

Commit policy:
- Commit `dvc.yaml` and `dvc.lock` when pipeline stages or dependencies change.
- Do not commit generated `data/*` outputs.

## Local execution notes

1. Provide Firestore/Redis/Google credentials via environment variables.
2. Start Airflow and trigger a DAG:

```bash
airflow dags list
airflow dags trigger daily_etl_pipeline
airflow dags trigger ketchup_comprehensive_pipeline
```

Airflow local config/runtime files can be generated with:

```bash
export AIRFLOW_HOME="$(pwd)/airflow_home"
airflow db init
```

This creates `airflow_home/airflow.cfg` and runtime files under `airflow_home/`.

3. `ketchup_comprehensive_pipeline` can gate heavy bias checks with:

```bash
airflow variables set run_extended_bias_analysis true
```
