terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.0"
    }
  }

  # Remote state (recommended). Create the bucket once, then uncomment:
  # backend "gcs" {
  #   bucket = "<your-tfstate-bucket>"
  #   prefix = "knowledge_gathering/deployments"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
