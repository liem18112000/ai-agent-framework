# Phase C — distributed scenario generation: a Pub/Sub push subscription fans batch jobs out to a
# Cloud Run worker service. Everything here is gated by var.deploy_workers (default false), so it is a
# no-op unless enabled. NOTE: not yet live-validated; workers share the per-project Vertex quota.
#
# Flow: TPD (coordinator, TPD_GEN_MODE=workers) publishes one job/batch -> topic tpd-gen-batches ->
#       push subscription POSTs each to the worker service -> worker writes result to GCS -> TPD polls.
# Auth: the push subscription mints an OIDC token for the runtime SA, which has run.invoker on the worker
#       (worker is allow_unauthenticated = false). Failures nack -> retried -> dead-lettered after 5 tries.

locals {
  workers_on   = var.deploy_workers ? 1 : 0
  worker_topic = "tpd-gen-batches"
}

data "google_project" "current" {
  count      = local.workers_on
  project_id = var.project_id
}

resource "google_pubsub_topic" "gen_batches" {
  count = local.workers_on
  name  = local.worker_topic
}

resource "google_pubsub_topic" "gen_batches_dlq" {
  count = local.workers_on
  name  = "${local.worker_topic}-dlq"
}

# The worker Cloud Run service (reuses the shared image; entrypoint = uvicorn worker:app, the push handler).
module "worker" {
  source = "./modules/cloud_run_service"

  create                = var.deploy_workers
  name                  = "tpd-gen-worker"
  location              = var.region
  ingress               = var.ingress
  service_account_email = google_service_account.kga.email
  timeout               = "600s"
  min_instances         = 0
  max_instances         = var.worker_max_instances
  allow_unauthenticated = false # push authenticates via the runtime SA's OIDC token (run.invoker below)

  containers = [
    {
      name                     = "worker"
      image                    = var.image
      command                  = ["sh", "-c", "uvicorn worker:app --host 0.0.0.0 --port 8080"]
      ingress_port             = 8080
      cpu                      = var.cpu
      memory                   = var.memory
      cpu_idle                 = true
      startup_cpu_boost        = true
      probe_port               = 8080
      startup_probe_http_path  = "/livez"
      liveness_probe_http_path = "/livez"
      env = [
        { name = "GCS_BUCKET", value = google_storage_bucket.memory.name },
        { name = "VERTEX_PROJECT", value = var.project_id },
        { name = "VERTEX_LOCATION", value = var.vertex_region },
        { name = "VERTEX_MODEL", value = var.vertex_model },
        { name = "TPD_LOG", value = "1" },
        { name = "COMMON_LOG", value = "1" },
      ]
    },
  ]

  depends_on = [google_project_service.apis]
}

# The push subscription -> worker, dead-lettering to the DLQ after 5 failed deliveries.
resource "google_pubsub_subscription" "gen_batches_sub" {
  count = local.workers_on
  name  = "${local.worker_topic}-sub"
  topic = google_pubsub_topic.gen_batches[0].id

  ack_deadline_seconds       = 600
  message_retention_duration = "3600s"

  push_config {
    push_endpoint = module.worker.uri
    oidc_token {
      service_account_email = google_service_account.kga.email
    }
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.gen_batches_dlq[0].id
    max_delivery_attempts = 5
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
}

# --- IAM ---
# Coordinator (runtime SA, runs in TPD) publishes to the topic.
resource "google_pubsub_topic_iam_member" "coordinator_publish" {
  count  = local.workers_on
  topic  = google_pubsub_topic.gen_batches[0].id
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.kga.email}"
}

# The push OIDC token (runtime SA) must be allowed to invoke the worker service.
resource "google_cloud_run_v2_service_iam_member" "worker_invoker" {
  count    = local.workers_on
  name     = module.worker.name
  location = module.worker.location
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.kga.email}"
}

# The Pub/Sub service agent must be able to publish to the DLQ and consume the subscription for dead-lettering.
resource "google_pubsub_topic_iam_member" "dlq_publish" {
  count  = local.workers_on
  topic  = google_pubsub_topic.gen_batches_dlq[0].id
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:service-${data.google_project.current[0].number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_pubsub_subscription_iam_member" "dlq_subscribe" {
  count        = local.workers_on
  subscription = google_pubsub_subscription.gen_batches_sub[0].name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:service-${data.google_project.current[0].number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}
