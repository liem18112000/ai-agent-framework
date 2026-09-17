# ===========================================================================
# Cloud Run services for the Testing-Agent stack — SINGLE-GATEWAY topology (G2).
#
#   * mcp-gateway-v2 (ingress, :8080) — the ONE MCP endpoint Claude connects to; an A2A client of
#     all three agents. Holds the per-agent multi-turn task maps in memory → session_affinity + min=max=1.
#   * knowledge-gathering / test-plan-definition / test-evaluation — each an A2A-ONLY service
#     (single agent container, ingress :8080). Public + the shared A2A bearer is the gate; the gateway
#     calls them with that bearer. (Was a 2-container agent+bridge sidecar before G2.)
#
# All containers share ONE runtime SA (kga-runtime: Vertex + bucket + Cloud SQL + Atlassian + bearers).
# ===========================================================================

# --- the gateway's inbound bearer (Claude → gateway); read by the kga-runtime SA (runs the gateway) ---
resource "google_secret_manager_secret" "gateway_bearer" {
  count     = var.deploy_gateway ? 1 : 0
  secret_id = "${var.name_prefix}-gateway-bearer-token"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "gateway_bearer_access" {
  count     = var.deploy_gateway ? 1 : 0
  secret_id = google_secret_manager_secret.gateway_bearer[0].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.kga.email}"
}

# ---------------------------------------------------------------------------
# knowledge-gathering — A2A-only agent (ingress :8080). Crawls Atlassian; needs the bitbucket secret.
# ---------------------------------------------------------------------------
module "kga" {
  source = "./modules/cloud_run_service"

  create                = var.deploy_bridge
  name                  = var.service_name
  location              = var.region
  ingress               = var.ingress
  service_account_email = google_service_account.kga.email
  timeout               = "600s"
  session_affinity      = true
  min_instances         = var.bridge_min_instances
  max_instances         = var.bridge_max_instances
  cloudsql_instance     = local.cloudsql_connection_name
  allow_unauthenticated = var.bridge_allow_unauthenticated

  containers = [
    {
      name                     = "agent"
      image                    = var.image
      command                  = ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 8080"]
      ingress_port             = 8080
      cpu                      = var.cpu
      memory                   = var.memory
      cpu_idle                 = false # hold CPU between requests (keeps the multi-turn refine session live)
      startup_cpu_boost        = true
      mount_cloudsql           = true
      probe_port               = 8080
      startup_probe_http_path  = "/livez"
      liveness_probe_http_path = "/livez"
      env = concat(
        local.memory_env, # pgvector recall tier (inert under MEMORY_BACKEND=gcs)
        var.deploy_cloudsql ? [
          { name = "DB_INSTANCE_CONNECTION_NAME", value = local.cloudsql_connection_name },
          { name = "DB_NAME", value = var.db_name },
          { name = "DB_USER", value = var.db_user },
          { name = "DB_PASSWORD", secret = google_secret_manager_secret.db_password[0].secret_id },
        ] : [],
        [
          { name = "AGENT", value = "knowledge_gathering" },
          { name = "GCS_BUCKET", value = google_storage_bucket.memory.name },
          { name = "VERTEX_PROJECT", value = var.project_id },
          { name = "VERTEX_LOCATION", value = var.vertex_region },
          { name = "VERTEX_MODEL", value = var.vertex_model },
          { name = "ATLASSIAN_BASE_URL", value = var.atlassian_base_url },
          { name = "ATLASSIAN_EMAIL", value = var.atlassian_email },
          { name = "ATLASSIAN_API_TOKEN", secret = google_secret_manager_secret.atlassian_token.secret_id },
          { name = "ATLASSIAN_BITBUCKET_USERNAME", value = var.atlassian_email },
          { name = "ATLASSIAN_BITBUCKET_APP_PASSWORD", secret = google_secret_manager_secret.bitbucket_app_password.secret_id },
          { name = "A2A_BEARER_TOKEN", secret = google_secret_manager_secret.a2a_bearer.secret_id },
        ],
        [
          { name = "KGA_CAPTURE_LESSONS", value = "1" }, # L2/L3 self-learning capture
          { name = "KGA_RECALL_LESSONS", value = "1" },  # L4 recall prior grounded lessons
        ],
        # Cloud exploration tiers 5/6/7 — presence of the env matrix IS the toggle (no separate flag).
        var.gcp_env_matrix != "" ? [
          { name = "KGA_GCP_ENV_MATRIX", value = var.gcp_env_matrix },
        ] : [],
      )
    },
  ]

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_iam_member.atlassian_access,
    google_secret_manager_secret_iam_member.bitbucket_access,
    google_secret_manager_secret_iam_member.a2a_access,
    google_secret_manager_secret_version.db_password,
    google_secret_manager_secret_iam_member.db_password_access,
    google_project_iam_member.cloudsql_client,
  ]
}

# ---------------------------------------------------------------------------
# test-plan-definition — A2A-only agent (ingress :8080). No Atlassian (reads the pack).
# ---------------------------------------------------------------------------
module "tpd" {
  source = "./modules/cloud_run_service"

  create                = var.deploy_test_plan
  name                  = var.tpd_service_name
  location              = var.region
  ingress               = var.ingress
  service_account_email = google_service_account.kga.email
  timeout               = "600s"
  session_affinity      = true
  min_instances         = 1
  max_instances         = 1
  cloudsql_instance     = local.cloudsql_connection_name
  allow_unauthenticated = var.bridge_allow_unauthenticated

  containers = [
    {
      name                     = "agent"
      image                    = var.image
      command                  = ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 8080"]
      ingress_port             = 8080
      cpu                      = var.cpu
      memory                   = var.memory
      cpu_idle                 = false
      startup_cpu_boost        = true
      mount_cloudsql           = true
      probe_port               = 8080
      startup_probe_http_path  = "/livez"
      liveness_probe_http_path = "/livez"
      env = concat(
        local.memory_env,
        var.deploy_cloudsql ? [
          { name = "DB_INSTANCE_CONNECTION_NAME", value = local.cloudsql_connection_name },
          { name = "DB_NAME", value = var.db_name },
          { name = "DB_USER", value = var.db_user },
          { name = "DB_PASSWORD", secret = google_secret_manager_secret.db_password[0].secret_id },
        ] : [],
        [
          { name = "AGENT", value = "test_plan_definition" },
          { name = "GCS_BUCKET", value = google_storage_bucket.memory.name },
          { name = "VERTEX_PROJECT", value = var.project_id },
          { name = "VERTEX_LOCATION", value = var.vertex_region },
          { name = "VERTEX_MODEL", value = var.vertex_model },
        ],
        var.tpd_llm_detail ? [{ name = "TPD_LLM_DETAIL", value = "1" }] : [],
        [
          { name = "A2A_BEARER_TOKEN", secret = google_secret_manager_secret.a2a_bearer.secret_id },
          { name = "TPD_CAPTURE_LESSONS", value = "1" },
          { name = "TPD_RECALL_LESSONS", value = "1" },
          # Observability during the generation-quality debugging phase — surfaces the app loggers
          # (generator batch failures, scope classifier) to Cloud Logging. Remove once stabilised.
          { name = "TPD_LOG", value = "1" },
          { name = "COMMON_LOG", value = "1" },
        ]
      )
    },
  ]

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_iam_member.a2a_access,
    google_secret_manager_secret_version.db_password,
    google_secret_manager_secret_iam_member.db_password_access,
    google_project_iam_member.cloudsql_client,
  ]
}

# ---------------------------------------------------------------------------
# test-evaluation — A2A-only read-only scorer (ingress :8080). No Atlassian.
# ---------------------------------------------------------------------------
module "tev" {
  source = "./modules/cloud_run_service"

  create                = var.deploy_test_evaluation
  name                  = var.tev_service_name
  location              = var.region
  ingress               = var.ingress
  service_account_email = google_service_account.kga.email
  timeout               = "600s"
  session_affinity      = true
  min_instances         = 1
  max_instances         = 1
  cloudsql_instance     = local.cloudsql_connection_name
  allow_unauthenticated = var.bridge_allow_unauthenticated
  vpc_connector         = var.deploy_redis ? google_vpc_access_connector.redis[0].id : ""

  containers = [
    {
      name                     = "agent"
      image                    = var.image
      command                  = ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 8080"]
      ingress_port             = 8080
      cpu                      = var.cpu
      memory                   = var.memory
      cpu_idle                 = false
      startup_cpu_boost        = true
      mount_cloudsql           = true
      probe_port               = 8080
      startup_probe_http_path  = "/livez"
      liveness_probe_http_path = "/livez"
      env = concat(
        local.memory_env,
        var.deploy_cloudsql ? [
          { name = "DB_INSTANCE_CONNECTION_NAME", value = local.cloudsql_connection_name },
          { name = "DB_NAME", value = var.db_name },
          { name = "DB_USER", value = var.db_user },
          { name = "DB_PASSWORD", secret = google_secret_manager_secret.db_password[0].secret_id },
        ] : [],
        # Benchmark cache → Memorystore Redis (only when provisioned; else CACHE_BACKEND unset = NullCache).
        var.deploy_redis ? [
          { name = "CACHE_BACKEND", value = "redis" },
          { name = "REDIS_HOST", value = google_redis_instance.cache[0].host },
          { name = "REDIS_PORT", value = tostring(google_redis_instance.cache[0].port) },
        ] : [],
        [
          { name = "AGENT", value = "test_evaluation" },
          { name = "GCS_BUCKET", value = google_storage_bucket.memory.name },
          { name = "VERTEX_PROJECT", value = var.project_id },
          { name = "VERTEX_LOCATION", value = var.vertex_region },
          { name = "VERTEX_MODEL", value = var.vertex_model },
          { name = "A2A_BEARER_TOKEN", secret = google_secret_manager_secret.a2a_bearer.secret_id },
        ]
      )
    },
  ]

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_iam_member.a2a_access,
    google_secret_manager_secret_version.db_password,
    google_secret_manager_secret_iam_member.db_password_access,
    google_project_iam_member.cloudsql_client,
  ]
}

# ---------------------------------------------------------------------------
# admin_agent — A2A-only memory & history operator utility (ingress :8080). NOT part of the testing
# pipeline. Deterministic router, no LLM → no Vertex, no Atlassian. Needs GCS (the bank) + Cloud SQL
# (pgvector + the A2A task / ADK session tables it introspects and, on wipe_all, TRUNCATEs).
# ---------------------------------------------------------------------------
module "admin" {
  source = "./modules/cloud_run_service"

  create                = var.deploy_admin
  name                  = var.admin_service_name
  location              = var.region
  ingress               = var.ingress
  service_account_email = google_service_account.kga.email
  timeout               = "600s"
  session_affinity      = true
  min_instances         = 1
  max_instances         = 1
  cloudsql_instance     = local.cloudsql_connection_name
  allow_unauthenticated = var.bridge_allow_unauthenticated

  containers = [
    {
      name                     = "agent"
      image                    = var.image
      command                  = ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 8080"]
      ingress_port             = 8080
      cpu                      = var.cpu
      memory                   = var.memory
      cpu_idle                 = false
      startup_cpu_boost        = true
      mount_cloudsql           = true
      probe_port               = 8080
      startup_probe_http_path  = "/livez"
      liveness_probe_http_path = "/livez"
      env = concat(
        local.memory_env,
        var.deploy_cloudsql ? [
          { name = "DB_INSTANCE_CONNECTION_NAME", value = local.cloudsql_connection_name },
          { name = "DB_NAME", value = var.db_name },
          { name = "DB_USER", value = var.db_user },
          { name = "DB_PASSWORD", secret = google_secret_manager_secret.db_password[0].secret_id },
        ] : [],
        [
          { name = "AGENT", value = "admin_agent" },
          { name = "GCS_BUCKET", value = google_storage_bucket.memory.name },
          { name = "A2A_BEARER_TOKEN", secret = google_secret_manager_secret.a2a_bearer.secret_id },
        ]
      )
    },
  ]

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_iam_member.a2a_access,
    google_secret_manager_secret_version.db_password,
    google_secret_manager_secret_iam_member.db_password_access,
    google_project_iam_member.cloudsql_client,
  ]
}

# ---------------------------------------------------------------------------
# mcp-gateway-v2 — the single MCP endpoint. One container running `python -m gateway`
# (GATEWAY_TRANSPORT=http). An A2A client of the three agents (their service URLs + the shared
# A2A bearer); gated inbound by GATEWAY_BEARER_TOKEN. Holds per-agent task maps in memory →
# session_affinity + min=max=1. No Cloud SQL (stateless w.r.t. the DB; talks only A2A).
# ---------------------------------------------------------------------------
module "gateway" {
  source = "./modules/cloud_run_service"

  create                = var.deploy_gateway
  name                  = var.gateway_service_name
  location              = var.region
  ingress               = var.ingress
  service_account_email = google_service_account.kga.email
  timeout               = "600s"
  session_affinity      = true
  min_instances         = var.bridge_min_instances
  max_instances         = 1
  allow_unauthenticated = var.bridge_allow_unauthenticated

  containers = [
    {
      name                     = "gateway"
      image                    = var.image
      command                  = ["python", "-m", "gateway"]
      ingress_port             = 8080
      cpu                      = var.bridge_cpu
      memory                   = var.bridge_memory
      cpu_idle                 = false
      startup_cpu_boost        = true
      startup_probe_http_path  = "/livez"
      liveness_probe_http_path = "/livez"
      env = [
        { name = "GATEWAY_TRANSPORT", value = "http" },
        { name = "KGA_A2A_URL", value = var.deploy_bridge ? "${module.kga.uri}/" : "" },
        { name = "TPD_A2A_URL", value = var.deploy_test_plan ? "${module.tpd.uri}/" : "" },
        { name = "TEV_A2A_URL", value = var.deploy_test_evaluation ? "${module.tev.uri}/" : "" },
        { name = "ADMIN_A2A_URL", value = var.deploy_admin ? "${module.admin.uri}/" : "" },
        { name = "A2A_BEARER_TOKEN", secret = google_secret_manager_secret.a2a_bearer.secret_id },
        { name = "GATEWAY_BEARER_TOKEN", secret = google_secret_manager_secret.gateway_bearer[0].secret_id },
        { name = "BENCHMARK_ON_FINISH", value = "1" }, # eager-benchmark a run when implement_plan finishes
      ]
    },
  ]

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_iam_member.a2a_access,
    google_secret_manager_secret_iam_member.gateway_bearer_access,
  ]
}
