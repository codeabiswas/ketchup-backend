# Service account for the backend Cloud Run service
resource "google_service_account" "backend" {
  account_id   = "ketchup-backend-${var.environment}"
  display_name = "Ketchup Backend API"
}

# Service account for the analytics Cloud Run Job + Scheduler trigger
resource "google_service_account" "analytics" {
  account_id   = "ketchup-analytics-${var.environment}"
  display_name = "Ketchup Analytics Materialization"
}

# --- Backend SA permissions ---

# Read all runtime secrets
resource "google_project_iam_member" "backend_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

# Connect to Cloud SQL via Auth Proxy
resource "google_project_iam_member" "backend_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

# --- Analytics SA permissions ---

# Read DATABASE_URL secret
resource "google_secret_manager_secret_iam_member" "analytics_db_secret_accessor" {
  secret_id = google_secret_manager_secret.database_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.analytics.email}"
}

# Connect to Cloud SQL via Auth Proxy
resource "google_project_iam_member" "analytics_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.analytics.email}"
}

# Allow Cloud Scheduler to trigger the Cloud Run Job (run.jobs.run permission)
resource "google_project_iam_member" "analytics_run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.analytics.email}"
}
