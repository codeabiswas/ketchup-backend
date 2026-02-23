# Enable required GCP APIs
resource "google_project_service" "enabled_apis" {
  for_each = toset([
    "run.googleapis.com",             # Cloud Run
    "firestore.googleapis.com",       # Firestore
    "redis.googleapis.com",           # Memorystore (Redis)
    "secretmanager.googleapis.com",   # Secret Manager
    "artifactregistry.googleapis.com",# Artifact Registry
    "storage.googleapis.com",         # Cloud Storage
    "cloudbuild.googleapis.com"       # Cloud Build
  ])

  project = var.project_id
  service = each.key

  disable_on_destroy = false
}
