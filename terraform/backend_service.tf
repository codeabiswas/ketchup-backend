resource "google_cloud_run_v2_service" "backend" {
  name     = "ketchup-backend-${var.environment}"
  location = var.region

  template {
    service_account = google_service_account.backend.email

    containers {
      image = var.backend_image

      ports {
        container_port = 8000
      }

      # --- Plain environment variables ---
      env {
        name  = "VLLM_BASE_URL"
        value = var.vllm_base_url
      }
      env {
        name  = "VLLM_MODEL"
        value = var.vllm_model
      }
      env {
        name  = "FRONTEND_URL"
        value = var.frontend_url
      }
      env {
        name  = "PLANNER_FALLBACK_ENABLED"
        value = "false"
      }

      # --- Secret-backed environment variables ---
      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.database_url.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "GOOGLE_MAPS_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.google_maps_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "TAVILY_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.tavily_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "VLLM_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.vllm_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "BACKEND_INTERNAL_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.backend_internal_api_key.secret_id
            version = "latest"
          }
        }
      }

      # Cloud SQL Auth Proxy socket directory
      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      startup_probe {
        http_get {
          path = "/health"
          port = 8000
        }
        initial_delay_seconds = 10
        period_seconds        = 5
        failure_threshold     = 12
        timeout_seconds       = 5
      }
    }

    # Cloud SQL Auth Proxy sidecar (managed by Cloud Run)
    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.main.connection_name]
      }
    }

    scaling {
      min_instance_count = var.backend_min_instances
      max_instance_count = var.backend_max_instances
    }
  }

  depends_on = [
    google_project_service.enabled_apis,
    google_secret_manager_secret_version.database_url,
    google_project_iam_member.backend_secret_accessor,
    google_project_iam_member.backend_cloudsql_client,
  ]
}

# Allow unauthenticated (public) access to the backend API
resource "google_cloud_run_v2_service_iam_member" "backend_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
