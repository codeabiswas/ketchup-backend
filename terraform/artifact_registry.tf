# The backend AR repo is pre-created by the CI/CD workflow (before Terraform)
# so Docker push can succeed. It is NOT managed here to avoid conflicts.
# The vLLM repo is only created by Terraform (no workflow conflict).

resource "google_artifact_registry_repository" "vllm_repo" {
  location      = var.region
  repository_id = "ketchup-vllm-${var.environment}"
  description   = "Docker repository for Ketchup vLLM model-serving images"
  format        = "DOCKER"

  depends_on = [google_project_service.enabled_apis]
}
