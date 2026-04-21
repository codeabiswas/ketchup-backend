# --- Secret placeholders ---
# Secrets are suffixed with `_${var.environment}` so dev and prod are fully
# isolated within the same project (e.g. DATABASE_URL_dev vs DATABASE_URL_prod).

resource "google_secret_manager_secret" "database_url" {
  secret_id = "DATABASE_URL_${var.environment}"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled_apis]
}

resource "google_secret_manager_secret" "google_maps_api_key" {
  secret_id = "GOOGLE_MAPS_API_KEY_${var.environment}"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled_apis]
}

resource "google_secret_manager_secret" "tavily_api_key" {
  secret_id = "TAVILY_API_KEY_${var.environment}"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled_apis]
}

resource "google_secret_manager_secret" "vllm_api_key" {
  secret_id = "VLLM_API_KEY_${var.environment}"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled_apis]
}

resource "google_secret_manager_secret" "backend_internal_api_key" {
  secret_id = "BACKEND_INTERNAL_API_KEY_${var.environment}"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled_apis]
}

resource "google_secret_manager_secret" "hf_token" {
  secret_id = "HF_TOKEN_${var.environment}"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled_apis]
}

resource "google_secret_manager_secret" "smtp_password" {
  secret_id = "SMTP_PASSWORD_${var.environment}"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled_apis]
}

# --- DATABASE_URL secret version (set automatically from the Cloud SQL instance) ---
# Cloud Run connects via the Cloud SQL Auth Proxy Unix socket mounted at /cloudsql.

resource "google_secret_manager_secret_version" "database_url" {
  secret = google_secret_manager_secret.database_url.id

  secret_data = "postgresql://postgres:${random_password.db_password.result}@/appdb?host=/cloudsql/${google_sql_database_instance.main.connection_name}"
}

# --- Placeholder versions for secrets populated by CI/CD ---
# Cloud Run requires at least one version to exist for each referenced secret.
# These placeholders are overwritten by the GitHub Actions workflow with real values.

resource "google_secret_manager_secret_version" "google_maps_api_key" {
  secret      = google_secret_manager_secret.google_maps_api_key.id
  secret_data = "PLACEHOLDER"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

resource "google_secret_manager_secret_version" "tavily_api_key" {
  secret      = google_secret_manager_secret.tavily_api_key.id
  secret_data = "PLACEHOLDER"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

resource "google_secret_manager_secret_version" "vllm_api_key" {
  secret      = google_secret_manager_secret.vllm_api_key.id
  secret_data = "PLACEHOLDER"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

resource "google_secret_manager_secret_version" "backend_internal_api_key" {
  secret      = google_secret_manager_secret.backend_internal_api_key.id
  secret_data = "PLACEHOLDER"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

resource "google_secret_manager_secret_version" "hf_token" {
  secret      = google_secret_manager_secret.hf_token.id
  secret_data = "PLACEHOLDER"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

resource "google_secret_manager_secret_version" "smtp_password" {
  secret      = google_secret_manager_secret.smtp_password.id
  secret_data = "PLACEHOLDER"

  lifecycle {
    ignore_changes = [secret_data]
  }
}
