# Secret Manager for API Keys
resource "google_secret_manager_secret" "api_keys" {
  secret_id = "ketchup-api-keys-${var.environment}"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled_apis]
}
