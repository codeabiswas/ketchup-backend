output "backend_url" {
  description = "URL of the deployed backend Cloud Run service"
  value       = google_cloud_run_v2_service.backend.uri
}

output "backend_service_account" {
  description = "Email of the backend service account"
  value       = google_service_account.backend.email
}

output "analytics_service_account" {
  description = "Email of the analytics service account"
  value       = google_service_account.analytics.email
}

output "cloud_sql_instance_name" {
  description = "Cloud SQL instance name"
  value       = google_sql_database_instance.main.name
}

output "cloud_sql_connection_name" {
  description = "Cloud SQL connection name (PROJECT:REGION:INSTANCE) — use this in vLLM or local Cloud SQL Auth Proxy"
  value       = google_sql_database_instance.main.connection_name
}

output "backend_artifact_registry_url" {
  description = "Artifact Registry URL for backend images"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/ketchup-backend-${var.environment}"
}

output "vllm_artifact_registry_url" {
  description = "Artifact Registry URL for vLLM images"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.vllm_repo.repository_id}"
}

output "dvc_storage_bucket" {
  description = "GCS bucket for DVC pipeline artifacts"
  value       = google_storage_bucket.dvc_storage.name
}

output "analytics_job_name" {
  description = "Name of the analytics Cloud Run Job"
  value       = google_cloud_run_v2_job.analytics_materialization.name
}

output "next_steps" {
  description = "Post-deployment checklist"
  value       = <<-EOT
    1. Populate secrets that were not auto-set:
         printf "%s" "$GOOGLE_MAPS_API_KEY" | gcloud secrets versions add GOOGLE_MAPS_API_KEY --data-file=-
         printf "%s" "$TAVILY_API_KEY"      | gcloud secrets versions add TAVILY_API_KEY      --data-file=-
         printf "%s" "$VLLM_API_KEY"        | gcloud secrets versions add VLLM_API_KEY        --data-file=-
         printf "%s" "$BACKEND_INTERNAL_API_KEY" | gcloud secrets versions add BACKEND_INTERNAL_API_KEY --data-file=-
         printf "%s" "$HF_TOKEN"            | gcloud secrets versions add HF_TOKEN            --data-file=-

    2. Run DB migrations (first deploy):
         gcloud run jobs execute ketchup-analytics-materialization-${var.environment} --region ${var.region}

    3. Build and push the backend image:
         docker build -t ${var.region}-docker.pkg.dev/${var.project_id}/ketchup-backend-${var.environment}/ketchup-backend:latest .
         docker push ${var.region}-docker.pkg.dev/${var.project_id}/ketchup-backend-${var.environment}/ketchup-backend:latest

    4. Deploy vLLM (optional, GPU Cloud Run):
         ./scripts/deploy_vllm_cloud_run.sh ${var.project_id} ${var.region}
       Then update vllm_base_url in terraform.tfvars and re-run terraform apply.

    5. Verify:
         curl $(terraform output -raw backend_url)/health
  EOT
}
