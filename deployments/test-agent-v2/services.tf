# ===========================================================================
# Cloud Run services for the Testing-Agent stack — SIDECAR topology.
#
# One service PER AGENT, each with two containers on the SAME image:
#   * bridge  (ingress, :8080)  — serves MCP /mcp to Claude; A2A client of the agent
#   * agent   (sidecar)         — the A2A server, reachable ONLY on localhost:8081
#
# The agent is never internet-exposed; Claude reaches the bridge, the bridge reaches the
# agent over localhost (no public agent URL, no cross-service hop). All containers in a
# service share ONE runtime SA — the broad kga-runtime (Vertex + bucket + Cloud SQL +
# Atlassian + the bearer secrets). Session state lives in the bridge's memory, so each
# service pins to a single warm instance (session_affinity + min=max=1).
# ===========================================================================

# --- kga-runtime also reads the two bridge inbound-bearer secrets (it runs the bridges now) ---
resource "google_secret_manager_secret_iam_member" "bridge_bearer_access" {
  count     = var.deploy_bridge ? 1 : 0
  secret_id = google_secret_manager_secret.bridge_bearer[0].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.kga.email}"
}

resource "google_secret_manager_secret" "bridge_bearer" {
  count     = var.deploy_bridge ? 1 : 0
  secret_id = "${var.name_prefix}-bridge-bearer-token"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret" "tpd_bridge_bearer" {
  count     = var.deploy_test_plan ? 1 : 0
  secret_id = "${var.name_prefix}-tpd-bridge-bearer-token"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "tpd_bridge_bearer_access" {
  count     = var.deploy_test_plan ? 1 : 0
  secret_id = google_secret_manager_secret.tpd_bridge_bearer[0].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.kga.email}"
}

# ---------------------------------------------------------------------------
# knowledge-gathering — bridge (ingress) + agent (sidecar)
# ---------------------------------------------------------------------------
module "kga" {
  source = "./modules/cloud_run_service"

  create                = var.deploy_bridge
  name                  = var.service_name
  location              = var.region
  ingress               = var.ingress
  service_account_email = google_service_account.kga.email
  timeout               = "600s"
  session_affinity      = true # bridge holds the multi-turn refine session in memory
  min_instances         = var.bridge_min_instances
  max_instances         = var.bridge_max_instances
  cloudsql_instance     = local.cloudsql_connection_name
  allow_unauthenticated = var.bridge_allow_unauthenticated

  containers = [
    {
      name                   = "bridge"
      image                  = var.image
      command                = ["python", "-m", "knowledge_gathering.bridge"]
      ingress_port           = 8080
      cpu                    = var.bridge_cpu
      memory                 = var.bridge_memory
      cpu_idle               = false # hold CPU between requests (keeps the refine session live)
      startup_cpu_boost      = true
      startup_probe_tcp_port = 8080
      depends_on_containers  = ["agent"] # start the agent sidecar first
      env = [
        { name = "KGA_BRIDGE_TRANSPORT", value = "http" },
        { name = "KGA_A2A_URL", value = "http://localhost:8081/" }, # the agent sidecar
        { name = "A2A_BEARER_TOKEN", secret = google_secret_manager_secret.a2a_bearer.secret_id },
        { name = "KGA_BRIDGE_BEARER_TOKEN", secret = one(google_secret_manager_secret.bridge_bearer[*].secret_id) },
      ]
    },
    {
      name                     = "agent"
      image                    = var.image
      command                  = ["sh", "-c", "uvicorn knowledge_gathering.adk_app:app --host 0.0.0.0 --port 8081"]
      cpu                      = var.cpu
      memory                   = var.memory
      mount_cloudsql           = true
      probe_port               = 8081
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
        # G2-G5 self-exploration stack (default OFF; enabled via var.kga_self_explore).
        var.kga_self_explore ? [
          { name = "KGA_LLM_HYPOTHESIZE", value = "1" }, # G2 LLM-focused search terms (round-0)
          { name = "KGA_FOLLOW_WEB", value = "1" },      # G3 fetch ticket-linked external web
          { name = "KGA_LLM_LEADS", value = "1" },       # G4 external-LLM leads + grounding gate
          { name = "KGA_EXPLORE_LOOP", value = "1" },    # G5 bounded, resumable explore loop
        ] : [],
        [
          { name = "KGA_CAPTURE_LESSONS", value = "1" }, # L2/L3 self-learning capture (set 1 to enable)
          { name = "KGA_RECALL_LESSONS", value = "1" },  # L4 recall prior grounded lessons (set 1 to enable)
        ],
      )
    },
  ]

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_iam_member.atlassian_access,
    google_secret_manager_secret_iam_member.bitbucket_access,
    google_secret_manager_secret_iam_member.a2a_access,
    google_secret_manager_secret_iam_member.bridge_bearer_access,
    google_secret_manager_secret_version.db_password,
    google_secret_manager_secret_iam_member.db_password_access,
    google_project_iam_member.cloudsql_client,
  ]
}

# ---------------------------------------------------------------------------
# test-plan-definition — bridge (ingress) + agent (sidecar). Same kga-runtime SA,
# shared bucket + a2a bearer, no Atlassian (it reads the pack, it does not crawl).
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
      name                   = "bridge"
      image                  = var.image
      command                = ["python", "-m", "test_plan_definition.bridge"]
      ingress_port           = 8080
      cpu                    = "1"
      memory                 = "512Mi"
      cpu_idle               = false
      startup_cpu_boost      = true
      startup_probe_tcp_port = 8080
      depends_on_containers  = ["agent"]
      env = [
        { name = "TPD_BRIDGE_TRANSPORT", value = "http" },
        { name = "TPD_A2A_URL", value = "http://localhost:8081/" },
        { name = "A2A_BEARER_TOKEN", secret = google_secret_manager_secret.a2a_bearer.secret_id },
        { name = "TPD_BRIDGE_BEARER_TOKEN", secret = one(google_secret_manager_secret.tpd_bridge_bearer[*].secret_id) },
      ]
    },
    {
      name                     = "agent"
      image                    = var.image
      command                  = ["sh", "-c", "uvicorn test_plan_definition.adk_app:app --host 0.0.0.0 --port 8081"]
      cpu                      = var.cpu
      memory                   = var.memory
      mount_cloudsql           = true
      probe_port               = 8081
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
          { name = "GCS_BUCKET", value = google_storage_bucket.memory.name },
          { name = "VERTEX_PROJECT", value = var.project_id },
          { name = "VERTEX_LOCATION", value = var.vertex_region },
          { name = "VERTEX_MODEL", value = var.vertex_model },
        ],
        var.tpd_llm_detail ? [{ name = "TPD_LLM_DETAIL", value = "1" }] : [],
        [
          { name = "A2A_BEARER_TOKEN", secret = google_secret_manager_secret.a2a_bearer.secret_id },
          { name = "TPD_CAPTURE_LESSONS", value = "1" }, # L3 self-learning capture (set 1 to enable)
          { name = "TPD_RECALL_LESSONS", value = "1" },  # L4 recall prior grounded lessons (set 1 to enable)
        ]
      )
    },
  ]

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_iam_member.a2a_access,
    google_secret_manager_secret_iam_member.tpd_bridge_bearer_access,
    google_secret_manager_secret_version.db_password,
    google_secret_manager_secret_iam_member.db_password_access,
    google_project_iam_member.cloudsql_client,
  ]
}

# test-evaluation — the pack-quality scorer. Mirrors module.tpd (no Atlassian). Reads packs from
# the shared memory bank via common; the bridge→agent hop is authed by the shared a2a_bearer, and
# (unlike KGA/TPD) the bridge has no app-level bearer of its own — nonprod, read-only scorer.
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

  containers = [
    {
      name                   = "bridge"
      image                  = var.image
      command                = ["python", "-m", "test_evaluation.bridge"]
      ingress_port           = 8080
      cpu                    = "1"
      memory                 = "512Mi"
      cpu_idle               = false
      startup_cpu_boost      = true
      startup_probe_tcp_port = 8080
      depends_on_containers  = ["agent"]
      env = [
        { name = "TEV_BRIDGE_TRANSPORT", value = "http" },
        { name = "TEV_A2A_URL", value = "http://localhost:8081/" },
        { name = "A2A_BEARER_TOKEN", secret = google_secret_manager_secret.a2a_bearer.secret_id },
      ]
    },
    {
      name                     = "agent"
      image                    = var.image
      command                  = ["sh", "-c", "uvicorn test_evaluation.adk_app:app --host 0.0.0.0 --port 8081"]
      cpu                      = var.cpu
      memory                   = var.memory
      mount_cloudsql           = true
      probe_port               = 8081
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
