# Bucket for DVC data storage
resource "google_storage_bucket" "dvc_storage" {
  name          = "${var.project_id}-dvc-storage-${var.environment}"
  location      = var.region
  force_destroy = true

  uniform_bucket_level_access = true

  depends_on = [google_project_service.enabled_apis]
}

# TODO: create bucjet for tf state
# resource "google_storage_bucket" "terraform_state" {
#   name          = "${var.project_id}-terraform-state"
#   location      = var.region
#   force_destroy = false
#
#   versioning {
#     enabled = true
#   }
# }
