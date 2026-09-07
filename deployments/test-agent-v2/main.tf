locals {
  bucket_name = var.bucket_name != "" ? var.bucket_name : "${var.project_id}-${var.name_prefix}-memory"
}

# ---------------------------------------------------------------------------
# Enabled APIs
# ---------------------------------------------------------------------------
resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "aiplatform.googleapis.com",
    "storage.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "sqladmin.googleapis.com",
  ])
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# ---------------------------------------------------------------------------
# Artifact Registry (container image lives here)
# ---------------------------------------------------------------------------
resource "google_artifact_registry_repository" "images" {
  location      = var.region
  repository_id = var.artifact_repo
  format        = "DOCKER"
  description   = "Knowledge-Gathering agent container images"
  depends_on    = [google_project_service.apis]
}

# ---------------------------------------------------------------------------
# Memory bank bucket (markdown notes + index + run-logs)
# ---------------------------------------------------------------------------
resource "google_storage_bucket" "memory" {
  name                        = local.bucket_name
  location                    = var.bucket_location
  uniform_bucket_level_access = true
  force_destroy               = false

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      num_newer_versions = 5
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------------------
# Runtime service account + least-privilege IAM
# ---------------------------------------------------------------------------
resource "google_service_account" "kga" {
  account_id   = var.service_account_id
  display_name = "Knowledge-Gathering Test Agent (Cloud Run runtime)"
}

# Vertex AI (Claude on Vertex) — the Distill step
resource "google_project_iam_member" "vertex_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.kga.email}"
}

# Read/write the memory bank only
resource "google_storage_bucket_iam_member" "bucket_object_admin" {
  bucket = google_storage_bucket.memory.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.kga.email}"
}

# ---------------------------------------------------------------------------
# Secrets (containers only — add versions out-of-band, never in tfvars)
# ---------------------------------------------------------------------------
resource "google_secret_manager_secret" "atlassian_token" {
  secret_id = "${var.name_prefix}-atlassian-api-token"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret" "a2a_bearer" {
  secret_id = "${var.name_prefix}-a2a-bearer-token"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

# Bitbucket app password — read-only repo tarball downloads for the codegraph fetcher.
resource "google_secret_manager_secret" "bitbucket_app_password" {
  secret_id = "${var.name_prefix}-bitbucket-app-password"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "atlassian_access" {
  secret_id = google_secret_manager_secret.atlassian_token.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.kga.email}"
}

resource "google_secret_manager_secret_iam_member" "bitbucket_access" {
  secret_id = google_secret_manager_secret.bitbucket_app_password.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.kga.email}"
}

resource "google_secret_manager_secret_iam_member" "a2a_access" {
  secret_id = google_secret_manager_secret.a2a_bearer.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.kga.email}"
}

