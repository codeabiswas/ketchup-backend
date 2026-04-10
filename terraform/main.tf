terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }

  # State bucket is created in the bootstrap step (see deployment guide).
  # Bucket name and prefix are injected via -backend-config in CI/CD.
  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
}
