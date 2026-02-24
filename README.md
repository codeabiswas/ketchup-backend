# Ketchup Backend

This repository contains the backend API and a complete DAG-based data pipeline for the project.
The goal is to keep the pipeline simple, reproducible, and easy to run on another machine.

## 1) Overview

For this project phase, the pipeline is implemented with Airflow DAGs and DVC.
It covers the full workflow from data acquisition to preprocessing, validation, anomaly checks,
bias slicing, statistics generation, reporting, versioning, and monitoring.

Pipeline entry points:
- `pipelines/airflow/dags/daily_etl_dag.py`
- `pipelines/airflow/dags/comprehensive_etl_dag.py`
- `dvc.yaml`

Main DAG IDs:
- `daily_etl_pipeline`
- `ketchup_comprehensive_pipeline`

---

## 2) Key Components Included in This Pipeline

### 2.1 Data Acquisition
- Airflow tasks fetch data from source systems (Firestore and external APIs).
- DVC stage scripts fetch and save raw data under `data/raw/`.
- Reproducible commands are in `dvc.yaml` (`acquire_data`, `acquire_user_feedback`).

Relevant files:
- `scripts/acquire_data.py`
- `scripts/acquire_user_feedback.py`
- `utils/api_clients.py`
- `database/firestore_client.py`

### 2.2 Data Preprocessing
- Cleaning, transformation, and feature preparation are modularized.
- Preprocessing is reusable in both scripts and DAG tasks.
- Empty-input handling and missing-column safeguards are implemented for robust runs.

Relevant files:
- `scripts/preprocess_data.py`
- `pipelines/preprocessing.py`
- `pipelines/airflow/dags/comprehensive_etl_dag.py`

### 2.3 Test Modules
- Unit tests exist for pipeline components and edge cases.
- Tests include behavior for quality checks, profiling, and pipeline logic paths.

Relevant files:
- `tests/test_pipeline_components.py`

Run tests:
```bash
pytest tests/test_pipeline_components.py -v
```

### 2.4 Pipeline Orchestration (Airflow DAGs)
- Airflow manages task dependencies from extraction through final report generation.
- Parallel task structure is used where safe (for better flow/performance).
- Retry and task-level error handling are included.

Relevant files:
- `pipelines/airflow/dags/daily_etl_dag.py`
- `pipelines/airflow/dags/comprehensive_etl_dag.py`

### 2.5 Data Versioning with DVC
- Data stages are tracked in `dvc.yaml`.
- Outputs, metrics, and reports are versioned through DVC + Git workflow.

Relevant file:
- `dvc.yaml`

### 2.6 Tracking and Logging
- Airflow task logs are available in UI and `airflow-logs` volume.
- Script-level logging and DAG-level logging are used throughout.
- Pipeline monitoring/profiling utilities are included.

Relevant files:
- `pipelines/monitoring.py`
- `scripts/*.py`

### 2.7 Data Schema & Statistics Generation
- Schema and quality validation steps run in pipeline flow.
- Statistics are generated and written to `data/statistics/`.
- Directory creation and JSON serialization are handled safely.

Relevant files:
- `scripts/validate_data.py`
- `scripts/generate_statistics.py`
- `pipelines/validation.py`

### 2.8 Anomaly Detection & Alerts
- Anomaly checks are part of DVC stages and Airflow tasks.
- Validation/anomaly reports are generated in `data/reports/`.
- Failures are surfaced through task failures and logs.

Relevant files:
- `scripts/detect_anomalies.py`
- `pipelines/airflow/dags/comprehensive_etl_dag.py`

### 2.9 Pipeline Flow Optimization
- Airflow Gantt/Task Duration views are used to inspect bottlenecks.
- Runtime profiler returns bottleneck summaries.
- Extended bias branch is runtime-gated for faster default runs.

Relevant behavior:
- Airflow Variable: `run_extended_bias_analysis` (`false` by default)
- Output report includes bottlenecks in `data/reports/pipeline_report.json`

---

## 3) Data Bias Detection Using Data Slicing

### 3.1 Detecting Bias in Data
- Bias checks run as dedicated stages/tasks.
- The pipeline evaluates subgroup behavior through slicing outputs.

### 3.2 Data Slicing for Bias Analysis
- Slicing scripts are included and automated in `dvc.yaml`.
- Fairlearn-based slicing analysis is also included.

Relevant files:
- `scripts/detect_bias.py`
- `scripts/bias_slice.py`
- `scripts/fairlearn_bias_slicing.py`
- `scripts/synthetic_bias_slicing_eval.py`

### 3.3 Mitigation of Bias
- Workflow supports mitigation iterations by updating preprocessing/sampling/threshold logic.
- Extended branch in comprehensive DAG can run deeper fairness analysis when needed.

### 3.4 Documentation of Bias Mitigation
- Reports are written to `data/reports/` and tracked in pipeline outputs.
- This README and pipeline report files document how bias checks are run.

---

## 4) Additional Guidelines (Implemented)

### 4.1 Folder Structure

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
└─ README.md
```

### 4.2 README Documentation
This README includes:
- Environment setup
- Steps to run DAGs and DVC pipeline
- Code structure summary
- Reproducibility and data versioning workflow

### 4.3 Reproducibility
Anyone should be able to:
1. Clone the repository
2. Install dependencies
3. Start local services
4. Run DVC and/or Airflow pipeline
5. Reproduce outputs and reports

### 4.4 Code Style
- Modular files by concern (`scripts`, `pipelines`, `services`, `utils`).
- Python code follows readable, maintainable structure.
- `pytest` tests exist for pipeline logic.

### 4.5 Error Handling & Logging
- Stage-level `try/except` with explicit task failures.
- Logs include failure reasons for troubleshooting.
- Pipeline handles common local-runtime failures (empty data, output directories, JSON serialization).

---

## 5) Evaluation Criteria Mapping

1. **Proper Documentation**: covered in this README and module READMEs.
2. **Modular Code**: split into scripts, pipelines, services, utils, agents.
3. **Airflow Orchestration**: DAGs under `pipelines/airflow/dags/`.
4. **Tracking and Logging**: Airflow + Python logging + profiler.
5. **DVC**: stages and outputs in `dvc.yaml`.
6. **Flow Optimization**: Gantt + bottleneck reporting.
7. **Schema/Statistics**: validation and stats generation modules.
8. **Anomaly Detection & Alerts**: dedicated anomaly stage/task and logs.
9. **Bias Detection/Mitigation**: slicing + fairlearn analysis path.
10. **Test Modules**: `tests/test_pipeline_components.py`.
11. **Reproducibility**: explicit runbook below.
12. **Error Handling and Logging**: implemented across scripts and DAG tasks.

---

## 6) Environment Setup

### 6.1 Prerequisites
- Python 3.11+
- Docker Desktop + Docker Compose
- Git
- DVC (`pip install dvc` if not installed)

### 6.2 Python Setup
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
# source .venv/bin/activate

pip install -r requirements.txt
```

---

## 7) Running the Pipeline

### 7.1 Start Local Services
```bash
docker compose up -d firestore-emulator redis airflow-postgres airflow-init airflow-scheduler airflow-webserver
```

Airflow UI:
- URL: `http://localhost:8081`
- Default local credentials: `admin / admin`

### 7.2 Run Airflow DAGs
```bash
# List DAGs
docker compose exec airflow-webserver airflow dags list

# Trigger comprehensive pipeline
docker compose exec airflow-webserver airflow dags trigger ketchup_comprehensive_pipeline

# Check run states
docker compose exec airflow-webserver airflow dags list-runs -d ketchup_comprehensive_pipeline --no-backfill
```

Optional extended bias branch:
```bash
docker compose exec airflow-webserver airflow variables set run_extended_bias_analysis true
# set back to default fast mode
docker compose exec airflow-webserver airflow variables set run_extended_bias_analysis false
```

### 7.3 Run DVC Pipeline
```bash
# Reproduce all DVC stages
dvc repro

# View tracked metrics/report outputs in data/
```

---

## 8) Reproducibility Runbook (Clone to Output)

```bash
git clone <repo-url>
cd ketchup-backend

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Start local dependencies
docker compose up -d firestore-emulator redis airflow-postgres airflow-init airflow-scheduler airflow-webserver

# Run DVC workflow
dvc repro

# Trigger Airflow comprehensive DAG
docker compose exec airflow-webserver airflow dags trigger ketchup_comprehensive_pipeline
```

Expected generated artifacts include:
- `data/processed/calendar_processed.csv`
- `data/metrics/*.json`
- `data/reports/*.json|*.md|*.txt`
- `data/statistics/*.json`

---

## 9) Useful Verification Commands

```bash
# Show task states for a specific run
docker compose exec airflow-webserver airflow tasks states-for-dag-run ketchup_comprehensive_pipeline <run_id>

# Rank slowest successful tasks by average runtime
docker compose exec airflow-postgres psql -U airflow -d airflow -c "select task_id, round(avg(extract(epoch from (end_date-start_date)))::numeric,2) as avg_s, count(*) from task_instance where dag_id='ketchup_comprehensive_pipeline' and state='success' and end_date is not null group by task_id order by avg_s desc;"
```

---

## 10) Troubleshooting (Common Local Issues)

### Firestore emulator DNS error in Airflow
If logs show `DNS resolution failed for firestore-emulator:8080`:
```bash
docker compose up -d firestore-emulator
docker compose ps firestore-emulator
```

### Empty data causing preprocessing/statistics issues
- Pipeline currently guards empty venue/calendar paths and missing columns.
- Statistics/report JSON writing handles NumPy scalar values.

---

## 11) Quick Summary

This repository already includes the required pipeline features for the assignment:
- Airflow DAG orchestration
- DVC versioned data workflow
- Preprocessing, validation, statistics, anomaly and bias stages
- Logging, tests, and reproducible run steps
- Flow optimization support via Airflow Gantt + bottleneck profiling
