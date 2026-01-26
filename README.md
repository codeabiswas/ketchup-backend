# 🍅 Ketchup (Backend): Autonomous Social Coordination

Ketchup is an autonomous social coordination platform designed to solve the "scheduling friction" that plagues small friend groups. The system addresses the needs of "The Non-Planners"—groups who want to hang out but fail due to decision paralysis and logistical hurdles. By acting as a proactive "5th friend," Ketchup autonomously scans calendars, manages shared budgets, and generates curated options to shift the group from consensus-seeking to **Satisfaction Optimization** .

---

## 🏗 Essential Project Information

### Core Philosophy

* **Context-Aware Itineraries:** Generates personalized logistics, such as carpooling assignments, based on real-time travel data.
* **Vibe Spectrum Engine:** Instead of binary choices, it offers 5 distinct options ranging from "Safe" to "Adventurous" .
* **Closed-Loop Learning:** A Retrospective Phase captures first-party behavioral feedback to update preferences for future cycles .

### Target Metrics

| Category | Metric | Target |
| --- | --- | --- |
| **ML** | RAGAS Faithfulness & Relevancy | > 0.8 |
| **System** | End-to-End Latency (p99) | < 5 minutes |
| **System** | Tool-Call Success Rate | > 95% |
| **Business** | Monthly Closure Rate | 100% |
| **Business** | Active Planning Time | < 5 minutes |

---

## 📁 Repository Structure

The `ketchup-backend` is organized following modular programming practices to ensure clarity and maintainability .

* **`apps/api/`**: FastAPI gateway and orchestration layer handling tool calling, validation, and routing.
* **`apps/vllm/`**: Configuration and manifests for the vLLM server and GPU-accelerated model serving.
* **`apps/tools/`**: Microservices for external integrations (Google Calendar, Maps, Yelp) with built-in retries and caching.
* **`pipelines/airflow/`**: DAGs for offline tasks including preference updates, embedding refreshes, and weekly bias checks.
* **`eval/`**: Golden eval set (~200 examples) and RAGAS scripts used for release gating .
* **`infra/gcp/`**: Infrastructure as Code (Terraform) for GKE clusters, BigQuery, and Firestore .
* **`ops/`**: Monitoring runbooks, alert definitions, and Grafana dashboard configurations.
* **`tests/`**: Unit and integration tests, particularly for data preprocessing and tool schema contracts .

---

## ⚙️ Installation Instructions

To replicate the environment and run the pipeline on a fresh machine, follow these steps:

### 1. Prerequisites

* **>Python 3.10+** and **Docker** installed.
* **GCP Account** with an active project and billing enabled.
* **API Keys**: Enabled Google Calendar API, Maps Platform, and Yelp Fusion API.

### 2. Environment Setup

```bash
# Clone the repository
git clone https://github.com/codeabiswas/ketchup-backend.git
cd ketchup-backend

# Install dependencies and tools
pip install -r requirements.txt
[cite_start]dvc pull  # Retrieve versioned data and artifacts [cite: 17, 70]

```

### 3. Infrastructure Deployment

Automated scripts handle the deployment to Google Kubernetes Engine (GKE):

```bash
cd infra/gcp
terraform init
[cite_start]terraform apply  # Provisions GKE cluster, Firestore, and BigQuery [cite: 464]

```

---

## 🚀 Usage Guidelines

### 1. Data Pipeline & Orchestration

The pipeline is structured using Airflow DAGs to handle the workflow from data acquisition to finalized output .

* **Triggering DAGs**: Access the Airflow UI to manually trigger `monthly_plan_initiation`.
* **Monitoring Flow**: Use the Airflow Gantt chart to identify bottlenecks and optimize slow tasks.

### 2. Model Evaluation & Bias Detection

Every release is gated by an automated evaluation pipeline:

* **Run Evals**: Execute `pytest eval/` to compute RAGAS metrics on the golden set.
* **Check Bias**: The pipeline performs data slicing to evaluate performance across different subgroups (age, gender, location) .
* **Alerts**: If bias or performance regression is detected, the pipeline triggers an alert and blocks deployment.

### 3. Real-Time Monitoring

The system uses Google Cloud Monitoring and Prometheus for observability:

* **Latency**: Track p99 response times for the LLM and tool calls.
* **Drift**: Weekly monitoring for data shift or model decay.
* **Retraining**: If performance drops below the predefined threshold, the CI/CD pipeline automatically triggers retraining.
