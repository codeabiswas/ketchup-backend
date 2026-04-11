# Random suffix so the instance name can be recreated after deletion
# (Cloud SQL prohibits reuse of the same name for ~7 days).
resource "random_id" "db_suffix" {
  byte_length = 4
}

resource "random_password" "db_password" {
  length  = 32
  special = false
}

resource "google_sql_database_instance" "main" {
  name             = "ketchup-${var.environment}-${random_id.db_suffix.hex}"
  database_version = "POSTGRES_16"
  region           = var.region

  settings {
    tier = var.db_instance_tier

    backup_configuration {
      enabled    = true
      start_time = "03:00"
    }

    ip_configuration {
      # Public IP is required for Cloud SQL Auth Proxy (used by Cloud Run).
      # No authorized networks are needed — the proxy authenticates via IAM.
      ipv4_enabled = true
    }
  }

  # Prevent accidental deletion in production.
  deletion_protection = var.environment == "prod"

  depends_on = [google_project_service.enabled_apis]
}

resource "google_sql_database" "app" {
  name     = "appdb"
  instance = google_sql_database_instance.main.name
}

resource "google_sql_user" "app" {
  name     = "postgres"
  instance = google_sql_database_instance.main.name
  password = random_password.db_password.result
}
