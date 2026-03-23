# Artifact Registry for Docker Images
resource "google_artifact_registry_repository" "backend_repo" {
  location      = var.region
  repository_id = "ketchup-backend-${var.environment}"
  description   = "Docker repository for Ketchup Backend"
  format        = "DOCKER"

  depends_on = [google_project_service.enabled_apis]
}

resource "google_artifact_registry_repository" "vllm_repo" {
  location      = var.region
  repository_id = "ketchup-vllm-${var.environment}"
  description   = "Docker repository for Ketchup vLLM model-serving images"
  format        = "DOCKER"

  depends_on = [google_project_service.enabled_apis]
}
