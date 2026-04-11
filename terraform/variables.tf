variable "project_id" {
  description = "The GCP project ID"
  type        = string
}

variable "region" {
  description = "The GCP region"
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Environment (dev, staging, prod)"
  type        = string
  default     = "dev"
}

# --- Backend API ---

variable "backend_image" {
  description = "Container image for the backend Cloud Run service (e.g. REGION-docker.pkg.dev/PROJECT/ketchup-backend-dev/ketchup-backend:latest)"
  type        = string
}

variable "vllm_base_url" {
  description = "Base URL of the vLLM service including /v1 (e.g. https://ketchup-vllm-abc123-uc.a.run.app/v1). Leave empty to deploy backend without LLM support."
  type        = string
  default     = ""
}

variable "vllm_model" {
  description = "Model name served by vLLM"
  type        = string
  default     = "Qwen/Qwen3-4B-Instruct-2507"
}

variable "frontend_url" {
  description = "Allowed CORS origin for the frontend"
  type        = string
  default     = "http://localhost:3001"
}

variable "backend_min_instances" {
  description = "Minimum number of backend Cloud Run instances"
  type        = number
  default     = 0
}

variable "backend_max_instances" {
  description = "Maximum number of backend Cloud Run instances"
  type        = number
  default     = 3
}

# --- Cloud SQL ---

variable "db_instance_tier" {
  description = "Cloud SQL machine tier (e.g. db-f1-micro, db-g1-small, db-custom-2-7680)"
  type        = string
  default     = "db-f1-micro"
}

# --- Analytics job ---

variable "analytics_job_image" {
  description = "Container image for the analytics materialization job. Defaults to backend_image when empty."
  type        = string
  default     = ""
}

variable "analytics_job_service_account_email" {
  description = "Service account for the analytics Cloud Run Job and Scheduler trigger. Created automatically when empty."
  type        = string
  default     = ""
}

variable "database_url_secret_name" {
  description = "Secret Manager secret name for DATABASE_URL"
  type        = string
  default     = "DATABASE_URL"
}

variable "analytics_job_schedule" {
  description = "Cron schedule for analytics materialization (UTC)"
  type        = string
  default     = "0 3 * * *"
}
