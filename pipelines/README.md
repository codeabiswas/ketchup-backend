# Ketchup Data Pipeline (MVP)

## Overview

The pipeline orchestrates data ingestion from external APIs, performs ETL preprocessing, and stores normalized data in Firestore and BigQuery.

---

## What's Included

### Core Components

1. **Configuration Management** (`config/settings.py`)
   - Environment-based settings using Pydantic
   - API keys and service endpoints
   - Feature flags and limits

2. **Data Models** (`models/schemas.py`)
   - Pydantic schemas for all data types
   - Validation rules built-in
   - Examples for documentation

3. **External API Clients** (`utils/api_clients.py`)
   - Google Calendar API integration
   - Google Maps API (Places & Routes)
   - Redis caching with configurable TTL
   - Automatic retries with exponential backoff

4. **Data Normalization** (`utils/data_normalizer.py`)
   - Convert API responses to canonical schemas
   - Data validation and quality checks
   - Deduplication logic
   - Token compression for LLM efficiency

5. **Database Layer** (`database/firestore_client.py`)
   - Firestore operations wrapper
   - CRUD operations for all entity types
   - Batch operations support
   - Singleton pattern for connection pooling

6. **Airflow DAGs** (`pipelines/airflow/dags/daily_etl_dag.py`, `pipelines/airflow/dags/comprehensive_etl_dag.py`)
   - Daily ETL orchestration
   - Parallel extraction tasks
   - Data normalization and validation
   - BigQuery sync and metrics reporting
   - Bottleneck-aware profiling (`PerformanceProfiler.get_bottlenecks`)
   - Runtime-gated extended bias analysis (`run_extended_bias_analysis` variable)

7. **FastAPI Server** (`api/main.py`)
   - Health check endpoints
   - Manual trigger endpoints for pipeline tasks
   - Pipeline status monitoring

8. **Unit Tests** (`tests/test_data_pipeline.py`)
   - Data normalization tests
   - Validation tests
   - API client tests
   - Mock-based testing for external dependencies

---

## Quick Start

### 1. Prerequisites

```bash
# Install Python 3.10+
python --version

# Install uv or pip
pip install --upgrade pip
```

### 2. Environment Setup

```bash
# Clone and navigate
cd ketchup-backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env

# Edit .env with your credentials
# GCP_PROJECT_ID, GOOGLE_MAPS_API_KEY, etc.
```

### 3. Run Local Development Server

```bash
# Start FastAPI server
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# Server runs at: http://localhost:8000
# Interactive docs: http://localhost:8000/docs
```

### 4. Run Tests

```bash
# Run all tests
pytest tests/ -v

# Run specific test module
pytest tests/test_data_pipeline.py -v

# Run with coverage
pytest tests/ --cov=. --cov-report=html
```

### 5. Simulate ETL Pipeline

```bash
# Test data extraction
python -c "from pipelines.airflow.dags.daily_etl_dag import extract_calendar_data; extract_calendar_data()"

# Test data normalization
python -c "from pipelines.airflow.dags.daily_etl_dag import normalize_and_validate; normalize_and_validate()"
```

### 6. Airflow Optimization Workflow

```bash
# Start Airflow services
docker compose up -d airflow-postgres airflow-init airflow-scheduler airflow-webserver

# Trigger optimized comprehensive DAG
docker compose exec airflow-webserver airflow dags unpause ketchup_comprehensive_pipeline
docker compose exec airflow-webserver airflow dags trigger ketchup_comprehensive_pipeline

# Optional: enable heavy extended bias branch for deep fairness analysis
docker compose exec airflow-webserver airflow variables set run_extended_bias_analysis true
```

Use Airflow UI at http://localhost:8081 and inspect:
- Gantt view (critical path and queue delay)
- Task Duration view (cross-run hotspots)

The generated pipeline report at `data/reports/pipeline_report.json` includes:
- `performance.bottlenecks`
- top-level `bottlenecks`

```bash
# Rank slowest tasks by average runtime in Airflow metadata DB
docker compose exec airflow-postgres psql -U airflow -d airflow -c "select task_id, round(avg(extract(epoch from (end_date-start_date)))::numeric,2) as avg_s, count(*) from task_instance where dag_id='ketchup_comprehensive_pipeline' and state='success' and end_date is not null group by task_id order by avg_s desc;"
```

---

## Data Flow

```
┌─────────────────────────────────────────┐
│     External APIs                       │
│  ├─ Google Calendar                     │
│  ├─ Google Maps (Places & Routes)       │
└────────────────────┬────────────────────┘
                     │
                     v
        ┌────────────────────────┐
        │   API Clients          │
        │  ├─ Caching (Redis)    │
        │  ├─ Retries            │
        │  └─ Error Handling     │
        └────────────┬───────────┘
                     │
                     v
        ┌────────────────────────┐
        │   Data Normalizer      │
        │  ├─ Schema Validation  │
        │  ├─ Deduplication      │
        │  └─ Quality Checks     │
        └────────────┬───────────┘
                     │
                     v
        ┌────────────────────────┐
        │   Firestore            │
        │  (Operational Store)   │
        └────────────┬───────────┘
                     │
                     v
        ┌────────────────────────┐
        │   BigQuery             │
        │  (Analytics Store)     │
        └────────────────────────┘
```

---

## 🔌 API Endpoints

### Health & Status

- `GET /health` – Service health check
- `GET /` – Root endpoint with version info
- `GET /api/v1/pipeline/status` – Current pipeline metrics

### Data Operations

- `POST /api/v1/calendar/extract?user_id=<user_id>` – Extract user calendar
- `POST /api/v1/venues/search?location=<city>&category=<type>` – Search venues

---

## Configuration

Create `.env` file from `.env.example`:

```env
# Required
GCP_PROJECT_ID=your-gcp-project
GOOGLE_MAPS_API_KEY=your-maps-key


# Optional (defaults provided)
REDIS_URL=redis://localhost:6379
CACHE_TTL_SECONDS=86400
API_TIMEOUT_SECONDS=30
LOG_LEVEL=INFO
```

---

## 🧪 Testing

### Provided Test Coverage

1. **Data Normalization** (8 tests)
   - Calendar normalization
   - Google Places normalization
   - Google Places normalization
   - Route calculation
   - Deduplication
   - Compression

2. **Data Validation** (5 tests)
   - Calendar intervals validation
   - Venue metadata validation
   - Rating ranges
   - Coordinate bounds

3. **API Clients** (Basic mocking)

   - Caching mechanism

Run all tests:

```bash
pytest tests/test_data_pipeline.py -v --cov
```

---

## Development

## Submission Guideline Mapping

### 1) Folder Structure

The repository follows the required structure pattern (mapped to current names):

```
/Project Repo
|- pipelines/
|  |- airflow/
|  |  |- dags/
|- data/
|- scripts/
|- tests/
|- logs/
|- dvc.yaml
\- README.md
```

### 2) README Coverage

- Environment setup: Quick Start section.
- Pipeline run steps: Simulate ETL Pipeline + Airflow Optimization Workflow.
- Code structure explanation: Project Structure section.
- Reproducibility and DVC: section below.

### 3) Reproducibility and DVC

```bash
# From repository root
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
# source .venv/bin/activate

pip install -r requirements.txt

# Optional if remote is configured
dvc pull

# Reproduce all stages from dvc.yaml
dvc repro
```

Expected outputs include:
- `data/raw/*.csv`
- `data/processed/*.csv`
- `data/reports/*.json|*.md|*.txt`
- `data/metrics/*.json`
- `data/statistics/*.json`

### 4) Code Style and Modularity

- Modular packages: `pipelines/`, `utils/`, `database/`, `services/`, `api/`.
- PEP 8 toolchain: `black`, `flake8`, `mypy`.

### 5) Error Handling and Logging

- Core scripts in `scripts/` include stage-level try/except handling with non-zero exit on failure.
- Structured logs are emitted for success/failure paths to simplify troubleshooting.
- Monitoring helpers are centralized in `pipelines/monitoring.py`.

### Project Structure

```
ketchup-backend/
├── config/
│   └── settings.py              # Configuration management
├── models/
│   └── schemas.py               # Pydantic models
├── database/
│   └── firestore_client.py       # Firestore integration
├── utils/
│   ├── api_clients.py            # External API wrappers
│   └── data_normalizer.py        # ETL preprocessing
├── api/
│   └── main.py                   # FastAPI server
├── pipelines/
│   └── airflow/
│       └── dags/
│           └── daily_etl_dag.py  # Airflow orchestration
├── tests/
│   └── test_data_pipeline.py     # Unit tests
├── requirements.txt              # Python dependencies
├── .env.example                  # Environment template
└── pytest.ini                    # Test configuration
```

### Code Style

- **Format:** Black (`black .`)
- **Lint:** Flake8 (`flake8 .`)
- **Type checking:** MyPy (`mypy .`)

### Common Tasks

```bash
# Format code
black .

# Lint code
flake8 .

# Type checking
mypy .

# Run tests with coverage
pytest tests/ --cov=. --cov-report=html

# Clean environment
rm -rf .venv venv __pycache__ .pytest_cache .mypy_cache
```

---

## Troubleshooting

### Redis Connection Issues

```bash
# Start Redis locally (requires redis-server)
redis-server

# Or test without Redis (app will operate without cache)
```

### GCP Credential Issues

```bash
# Set credentials via environment
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json
```

### API Rate Limits

The client implements automatic backoff:
- Max retries: 3
- Backoff factor: 0.5
- Status codes: 429, 500–504

---

## Documentation

- Full project README: [../README.md](../README.md)
- API documentation: http://localhost:8000/docs (interactive Swagger UI)

---

## Contributing

To contribute to the data pipeline:

1. Create feature branch: `git checkout -b feature/my-feature`
2. Make changes and add tests
3. Run test suite: `pytest tests/ -v`
4. Format code: `black .`
5. Submit PR with test results

---
