# Ketchup Backend

## Project Overview

**Ketchup** is a backend service developed to help friend groups coordinate social events. It aggregates user availability from calendars and suggests event options based on group preferences.

### The Problem
- `api/routes/*`: thin HTTP controllers
- `services/*`: business logic and data orchestration
- `agents/planning.py`: canonical LLM planner (OpenAI-compatible tool-calling)
- `agents/app/main.py`: deprecated compatibility stub (returns 410 on legacy agent endpoints)
- `database/*`: asyncpg connection and schema migration SQL
- `config/settings.py`: environment-based configuration

Coordinating schedules among friends can be difficult due to:
- **Lack of planning:** Groups often discuss meeting up but fail to set a concrete plan.
- **Logistics:** Coordinating transportation and locations is complex.
- **Indecision:** It is hard to choose an activity that everyone agrees on.

### The Solution

Ketchup automates the planning process by:
1. Scanning linked Google Calendars to find common free time.
2. Generating event options using AI agents (vLLM) based on location and preferences.
3. Facilitating a voting process to finalize the plan.

**Key Features:**
- **Group Management:** Create groups, invite friends, and manage roles.
- **Smart Suggestions:** AI-driven recommendations tailored to the group's "vibe".
- **Logistics Support:** Integration with Google Maps to estimate travel times.
- **Feedback Loop:** Future suggestions improve based on user ratings.

---

## Core Architecture

### Tech Stack

- **Framework:** FastAPI (Python 3.10+)
- **Database:** PostgreSQL (AsyncPG) for operational data.
- **AI/ML:** vLLM for local LLM inference (compatible with OpenAI API).
- **Infrastructure:** Docker Compose for local development.

### Key Components

* **Event Generation Agent:** Uses LLMs (e.g., Qwen) to generate distinct event options.
* **Service Layer:** Modular services for Users, Groups, Plans, and Auth.
* **Logistics Engine:** Calculates travel times using Google Maps.
* **Voting System:** Structured voting process to reach a decision.


### Target Metrics

| Category | Metric | Target | Description |
| --- | --- | --- | --- |
| **ML Accuracy** | Recommendation Quality | > 80% | Validated against holdout set |
| **Performance** | API Latency (p99) | < 5 min | End-to-end plan generation time |
| **Reliability** | Tool Success Rate | > 95% | External API call success rate |
| **Business** | Monthly Closure Rate | 100% | % of initiated plans that finalize |
| **Engagement** | Vote Participation | > 80% | % of users voting within 24h |

---

## Dataset Information & Data Architecture

### Data Card Summary

| Field | Details |
| --- | --- |
| **Purpose** | Power real-time autonomous planning engine with calendar availability, venue metadata, travel logistics, and behavioral feedback |
| **Primary Data Types** | Calendar availability, venue metadata, travel times, votes/comments, post-event ratings, preference embeddings |
| **Format** | JSON payloads via APIs; structured tables in BigQuery; documents in Firestore; vectors in Pinecone |
| **Update Frequency** | Real-time on request; feedback after events; offline jobs daily/weekly |
| **Scale** | ~200 examples in golden eval set; growing first-party interaction logs for continuous learning |
| **Known Biases** | Cold start problem; selection bias (only groups using platform); venue API coverage varies by city |

### External Data Sources

| Source | Usage | Access Pattern | Caching |
| --- | --- | --- | --- |
| **Google Calendar API** | Busy/free intervals for each user | Per recommendation request (not persisted) | N/A |
| **Google Maps Places API** | Venue metadata (rating, category, photos) | Per request; category-level fallback | 24h Redis TTL |
| **Google Maps Routes API** | Travel times, distances between users and venues | Per request; circuit breaker on outage | 24h Redis TTL |
| **First-Party Feedback** | Votes, comments, ratings, attendance | On submission; stored in Firestore + BigQuery | Real-time |

### Data Privacy & Compliance

- **GDPR Compliance:** Restricted OAuth scopes (calendar.readonly); all PII encrypted at rest and in transit
- **Portal Security:** Google Identity Services (OAuth 2.0) ensures only the specific friend group accesses their trip details
- **Pseudonymization:** Feedback stored with group/user ID references, not raw personal information
- **Data Retention:** Feedback retained indefinitely for preference learning; raw interaction logs for hypothesis tracking

### Data Management

- **Operational Store:** PostgreSQL (Users, Groups, Plans, Invites).
- **Vector Store:** Pinecone (Optional, for preference embeddings).
- **Caching:** Redis (Venue metadata, API responses).

### External Data Sources

| Source | Usage | Access Pattern |
| --- | --- | --- |
| **Google Calendar API** | Busy/free intervals for each user | Per recommendation request |
| **Google Maps Places API** | Venue metadata (rating, category) | Per request; cached in Redis |
| **Google Maps Routes API** | Travel times, distances | Per request |


---

## Deployment Infrastructure

### Deployment Infrastructure

- **Compute:** Local Docker / Cloud Run (planned)
- **Database:** PostgreSQL (Google Cloud SQL or local)
- **Vectors:** Pinecone (Optional)







Redis | Caching for external API responses


| **CI/CD Platform** | Cloud Build + GitHub Actions | Automated testing & deployment | PR eval gating before production merge |

### Required Services

- **FastAPI:** Main Application
- **PostgreSQL:** Relational Data
- **Redis:** Caching
- **vLLM:** AI Inference

---

## Monitoring

- **Prometheus + Grafana:** Infrastructure metrics (DB, Container, Latency)
- **Langfuse:** LLM Observability (Token usage, Latency, Tool calls)


---

## Success & Acceptance Criteria

### Success Criteria (Business & UX Outcomes)

1. **Planning Efficiency:** Reduce active portal time to < 5 minutes per month for planning workflow
2. **Successful Closure:** Achieve 100% monthly closure rate—every month results in finalized event plan
3. **Social Realization:** Maintain ≥ 90% Event Realization Rate for two consecutive planning cycles
4. **High User Satisfaction:** Maintain 70%+ positive feedback rate ("Loved" or "Liked" ratings)
5. **Consensus Quality:** Average consensus achieved on first or second option set (< 1.5 re-rolls per group)

### Acceptance Criteria (Technical & Functional)

1. **Option Generation:** Portal displays unique, constraint-compliant event options in 100% of planning cycles
2. **Logistics Accuracy:** System correctly assigns carpooling tasks with ≥ 95% accuracy for destinations >5 miles
3. **Engagement Threshold:** ≥ 80% of group members vote within 24 hours of email notification
4. **Performance Targets:** End-to-end latency (p99) < 5 minutes; tool-call success rate > 95%
5. **Output Quality:** RAGAS faithfulness > 0.8; relevancy > 0.8 on golden set and time-constrained holdout
6. **Feedback Consistency:** Feedback ratio (Loved/Disliked) consistently maintained > 1.0

---

## 📅 Project Timeline & Phases

### Phase 1: Data Pipeline & Foundations (Deadline: February 23, 2026)

**Focus:** Establish the Ketchup engine, automate data ingestion, ensure reproducibility

| Week | Dates | Backend Deliverables |
| --- | --- | --- |
| W1 | Mon, Jan 26 – Sun, Feb 1 | Implement Google Calendar and Maps API ingestion scripts; design ETL schema |
| W2 | Mon, Feb 2 – Sun, Feb 8 | Build Preprocessing Pipeline normalizing JSON payloads into BigQuery; set up Firestore models |
| W3 | Mon, Feb 9 – Sun, Feb 15 | Orchestrate workflow using Airflow DAGs; implement DVC for data versioning; create preference artifacts |
| W4 | Mon, Feb 16 – Mon, Feb 23 | Write Pytest unit tests for data cleaning; implement Slack/email anomaly alerts; finalize documentation |

### Phase 2: Model Development & Bias Detection (Deadline: March 23, 2026)

**Focus:** Implement 3-Strike Consensus engine, preference learning, and comprehensive bias detection

| Week | Dates | Backend Deliverables |
| --- | --- | --- |
| W5-W6 | Tue, Feb 24 – Mon, Mar 2 | Integrate LLM + Tool Calling for autonomous option generation; test on golden set |
| W7-W8 | Tue, Mar 3 – Mon, Mar 9 | Setup Langfuse for LLM tracing; MLFlow for experiment tracking; implement output validators |
| W9-W10 | Tue, Mar 10 – Mon, Mar 16 | Perform Data Slicing to detect bias across demographic subgroups; generate bias reports; identify mitigations |
| W11-W12 | Tue, Mar 17 – Mon, Mar 23 | Run RAGAS evaluations on golden set; push best model to Artifact Registry; prepare release notes |

### Phase 3: Deployment, Monitoring & Launch (Deadline: April 20, 2026)

**Focus:** Automate production deployment on GKE, implement real-time monitoring, prepare for Expo

| Week | Dates | Backend Deliverables |
| --- | --- | --- |
| W13-W14 | Tue, Mar 24 – Mon, Mar 30 | Containerize services with Docker; set up GKE cluster with Terraform; configure GPU node pools |
| W15-W16 | Tue, Mar 31 – Mon, Apr 6 | Implement CI/CD pipelines (Cloud Build + GitHub Actions); automate model redeployment on golden set pass |
| W17-W18 | Tue, Apr 7 – Mon, Apr 13 | Set up Prometheus/Grafana for real-time monitoring; implement auto-retraining trigger on quality drop |
| W19-W20 | Tue, Apr 14 – Mon, Apr 20 | Record production demo on fresh environment; live expo presentation; verify monitoring dashboards |

---

## Repository Structure

The `ketchup-backend` is organized following modular, production-ready patterns for clarity, testability, and maintainability:

### Core Directories

| Directory | Purpose |
| --- | --- |
| **`api/`** | FastAPI gateway and REST endpoints (routes for users, groups, events, recommendations); orchestration layer for tool calling, validation, routing |
| **`api/routes/`** | Organized API handlers following RESTful conventions |
| **`agents/`** | AI agents for planning orchestration, natural language processing, preference learning, and hypothesis tracking |
| **`services/`** | Core business logic: event planning, recommendations, calendar management, logistics coordination, feedback processing |
| **`models/`** | Domain objects, Pydantic schemas, database entities |
| **`database/`** | ORM layer, Firestore/BigQuery clients, data persistence abstractions |
| **`database/migrations/`** | Database schema migrations and version control |
| **`config/`** | Environment management, secret handling, feature flags, model registry |
| **`utils/`** | Helper functions: calendar operations, distance calculations, constraint resolution, data normalization |
| **`analytics/`** | Success metrics tracking: functional option generation audit, logistics accuracy validation, event realization rate |
| **`eval/`** | Golden eval set (~200 examples), RAGAS evaluation scripts, output validators, bias detection utilities |
| **`infra/gcp/`** | Terraform configurations for GKE, Firestore, BigQuery, Cloud Run, Artifact Registry, monitoring |
| **`ops/`** | Runbooks, alert definitions, Grafana dashboard JSON, cost tracking, disaster recovery procedures |
| **`tests/`** | Unit tests for API, Services, and Agents |

### Key Configuration Files

- **`requirements.txt`** – Python dependencies (FastAPI, Pydantic, google-cloud-*, langchain, SQLAlchemy, etc.)
- **`pytest.ini`** – Test configuration and markers
- **`.env.example`** – Template for environment variables (GCP credentials, API keys, model endpoints)
- **`Dockerfile`** – Multi-stage build for containerizing backend services
- **`docker-compose.yml`** – Local development environment with all dependencies

---

## Installation & Setup Instructions

To replicate the environment and run the system on a fresh machine:

### 1. Prerequisites

- **Python 3.10+**
- **Docker & Docker Compose**
- **PostgreSQL 16+** (if running locally without Docker)
- **API Keys:** Google Calendar API, Google Maps Platform

### 2. Environment Setup (using uv)

```bash
cd ketchup-backend

# Install dependencies and create virtual environment
uv sync

# Activate virtual environment
# On Windows
.venv\Scripts\activate
# On macOS/Linux
source .venv/bin/activate

# Set up environment variables
cp .env.example .env
# Edit .env with DATABASE_URL, VLLM_BASE_URL, Google Keys
```

### 2a. Environment Setup (using pip)

```bash
# Create Python virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Run with Docker (Recommended)

```bash
docker-compose up --build
```

This starts:
- FastAPI Backend (http://localhost:8000)
- PostgreSQL Database
- Redis Cache
- vLLM Service (if configured)

cd infra/gcp
terraform init

# Plan infrastructure changes
terraform plan -out=tfplan

# Apply infrastructure (provisions GKE cluster, Firestore, BigQuery, etc.)
terraform apply tfplan
```

### 4. Run Local Development

```bash
# From project root
docker-compose up -d  # Starts local Firestore emulator, Redis, etc.

# In separate terminal, start FastAPI server
python -m uvicorn api.main:app --reload
```

Health:

## Usage & Operations Guide

## Key Environment Variables

The system uses Airflow DAGs for coordinated data processing:
- `DATABASE_URL`
- `VLLM_BASE_URL`
- `VLLM_MODEL`
- `VLLM_API_KEY`
- `PLANNER_FALLBACK_ENABLED`
- `GOOGLE_MAPS_API_KEY`
- `TAVILY_API_KEY` (optional; enables web-search fallback)
- `BACKEND_INTERNAL_API_KEY`
- `FRONTEND_URL`
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`

## Auth Boundary

Most application routes expect:
- `X-User-Id` (UUID)
- optional `X-Internal-Auth` when `BACKEND_INTERNAL_API_KEY` is configured

In local stack, frontend proxy injects these headers server-side.

## API Surface (Current)

Auth:
- `POST /api/auth/google-signin`

Users:
- `GET /api/users/me`
- `PUT /api/users/me/preferences`
- `GET /api/users/me/availability`
- `PUT /api/users/me/availability`

Groups:
- `POST /api/groups`
- `GET /api/groups`
- `GET /api/groups/{group_id}`
- `PUT /api/groups/{group_id}`
- `POST /api/groups/{group_id}/invite`
- `POST /api/groups/{group_id}/invite/accept`
- `POST /api/groups/{group_id}/invite/reject`
- `PUT /api/groups/{group_id}/preferences`
- `POST /api/groups/{group_id}/availability`

Plans:
- `POST /api/groups/{group_id}/generate-plans`
- `GET /api/groups/{group_id}/plans/{round_id}`
- `POST /api/groups/{group_id}/plans/{round_id}/vote`
- `GET /api/groups/{group_id}/plans/{round_id}/results`
- `POST /api/groups/{group_id}/plans/{round_id}/refine`
- `POST /api/groups/{group_id}/plans/{round_id}/finalize`

Feedback:
- `POST /api/groups/{group_id}/events/{event_id}/feedback`
- `GET /api/groups/{group_id}/events/{event_id}/feedback`

## Planner Behavior (Current)

- Planner calls an OpenAI-compatible model via `VLLM_BASE_URL`.
- With `GOOGLE_MAPS_API_KEY`, planner uses tool grounding for places and directions.
- With `TAVILY_API_KEY`, planner enables `web_search` as an optional third tool and
  uses web-grounded fallback when maps search returns no venues.
- `web_search` is fallback-oriented; it may not be invoked when maps already returns viable venues.
- If structured planner output fails, backend can synthesize deterministic maps-grounded plans (`maps_fallback`) from gathered tool results.
- If maps grounding is empty but web fallback yields candidates, backend can synthesize deterministic `web_fallback` plans.
- If planner fails and `PLANNER_FALLBACK_ENABLED=true`, generic fallback plans can be returned (`fallback`).

## Validation Commands

```bash
# Access Airflow UI
open http://localhost:8080  # Local development

# Or access Cloud Composer UI in GCP Console

# Manually trigger monthly planning initiation
airflow dags trigger monthly_plan_initiation
```

**Key DAGs:**


### 2. Model Evaluation & Quality Gating

```bash


Access monitoring dashboards:

- **Prometheus:** `http://localhost:9090` (local) or GCP Monitoring Console
- **Grafana:** `http://localhost:3000` (local) or GCP dashboards
- **Langfuse:** Traces for LLM costs, latency, and quality
- **Cloud Monitoring:** GCP native monitoring for infrastructure metrics

---

## External References

- **Frontend Repository:** [codeabiswas/ketchup-frontend](https://github.com/codeabiswas/ketchup-frontend)
- **Documentation:** See `docs/` folder for detailed architecture, API specs, and runbooks
- **Data Pipeline Specification:** See attached `data_pipeline___MLOPS-1-2.pdf`

---

## Contributing

When contributing to Ketchup Backend:

1. Create a feature branch from `main`
2. Ensure all tests pass: `pytest tests/ -v`
3. Run evaluation gating: `pytest eval/`
4. Submit PR; eval status must pass before merge
5. Follow code style guide (Black formatting, type hints required)

---

## 📧 Contact & Support

For questions or issues, please open a GitHub issue or contact the team leads. See documentation for detailed runbooks and troubleshooting guides.
Tavily smoke test (inside backend container):

```bash
docker compose -f ketchup-local/docker-compose.yml exec -T backend env PYTHONPATH=/app \
  python -c "import asyncio,json; import agents.planning as planning; out=asyncio.run(planning._web_search(query='group activities for friends', location='Boston, MA', max_results=3)); print('ERROR:', out.get('error')); print('RESULT_COUNT:', len(out.get('results', []))); print(json.dumps(out.get('results', [])[:2], indent=2))"
```

If you use the local Docker stack, prefer running via `ketchup-local/docker-compose.yml`.
