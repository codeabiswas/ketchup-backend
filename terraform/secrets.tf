# Secret Manager for API Keys
resource "google_secret_manager_secret" "api_keys" {
  secret_id = "ketchup-api-keys-${var.environment}"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled_apis]
}

# TODO: secrets
# resource "google_secret_manager_secret_version" "api_keys_version" {
#   secret      = google_secret_manager_secret.api_keys.id
#   secret_data = "YOUR_SECRET_DATA"
# }
