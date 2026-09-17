variable "project_id" {
  type        = string
  description = "GCP project that hosts the agent."
}

variable "region" {
  type        = string
  description = "Region for Cloud Run + Artifact Registry."
  default     = "europe-west6"
}

variable "vertex_region" {
  type        = string
  description = "Vertex AI location for model calls. Use global for Claude models — the only region that serves claude-sonnet-5 for this project."
  default     = "global"
}

variable "vertex_model" {
  type        = string
  description = "Vertex AI model id for the Distill step. Default claude-sonnet-5 (Claude on Vertex; requires vertex_region=global)."
  default     = "claude-sonnet-5"
}

variable "vertex_model_fast" {
  type        = string
  description = "Vertex AI model id for the FAST tier (cheap classification/judging: distill, restate, critique, assured judge). Empty = disabled (those calls use vertex_model). Set e.g. claude-haiku-4-5 to speed them up. Injected into KGA + TPD."
  default     = ""
}

variable "turbo" {
  type        = bool
  description = "Turbo latency profile (TESTAGENT_TURBO) for KGA + TPD: 1 assured iteration, no per-round interrogation critique, 1 refine pass. Trades a little quality for speed. Off = full quality."
  default     = false
}

# --- Two-tier memory (pgvector recall) — all inert under the default gcs backend ---
variable "memory_backend" {
  type        = string
  description = "Recall backend for the shared memory: 'gcs' (substring graph, default — no behaviour change), 'hybrid' (read pgvector, fall back to the graph — safe dark launch), or 'postgres' (pgvector authoritative). GCS stays the write source of truth under all three."
  default     = "gcs"
}

variable "memory_embed_model" {
  type        = string
  description = "Vertex text-embedding model for the pgvector recall tier. Multilingual (Swiss/German + EN) by default."
  default     = "text-multilingual-embedding-002"
}

variable "memory_embed_dims" {
  type        = string
  description = "Embedding width; MUST match the memory_node.embedding vector(N) column and the model's output dims. Changing it needs a column migration + full re-embed."
  default     = "768"
}

variable "memory_embed_location" {
  type        = string
  description = "Vertex REGION for embeddings. Must be a real region — the vertexai SDK 404s on 'global' for embedding models (unlike Claude, which uses vertex_region=global). Separate from vertex_region."
  default     = "us-central1"
}

variable "memory_drain_budget_s" {
  type        = string
  description = "Wall-clock seconds the head-of-request pgvector projector drain may run before deferring the rest to the next request. Keeps user requests snappy under slow embedding. Raise for faster bulk populate."
  default     = "8"
}

variable "memory_semantic_seed" {
  type        = string
  description = "Enable G0.5 semantic self-seed (vector-nearest, B5-grounded prior seeds at gather). Opt-in ('1') and only under a DB backend; empty = off (substring+B4 seeding only). Off by default because it changes the tuned de-bias seeding."
  default     = ""
}

variable "name_prefix" {
  type        = string
  description = "Prefix for named resources (v2 stack — distinct from v1's 'kga')."
  default     = "kga-v2"
}

variable "service_name" {
  type        = string
  description = "knowledge-gathering Cloud Run service name (A2A-only agent, ingress :8080)."
  default     = "knowledge-gathering-agent-v2"
}

variable "service_account_id" {
  type        = string
  description = "Runtime service account id (account_id part)."
  default     = "kga-v2-runtime"
}

variable "artifact_repo" {
  type        = string
  description = "Artifact Registry (Docker) repository id for the container image."
  default     = "kga"
}

variable "image" {
  type        = string
  description = "Full container image ref to deploy (e.g. <region>-docker.pkg.dev/<proj>/kga/kga:latest). Leave empty on first apply; set after the first push."
  default     = "us-docker.pkg.dev/cloudrun/container/hello" # placeholder so the service can be created before the real image exists
}

variable "bucket_name" {
  type        = string
  description = "Memory-bank bucket name (globally unique). Defaults to <project_id>-kga-memory."
  default     = ""
}

variable "bucket_location" {
  type        = string
  description = "GCS location for the memory bank."
  default     = "EU"
}

variable "atlassian_base_url" {
  type        = string
  description = "Atlassian Cloud base URL, e.g. https://axonivy.atlassian.net"
}

variable "atlassian_email" {
  type        = string
  description = "Atlassian account email used with the API token (non-secret)."
}

variable "min_instances" {
  type        = number
  description = "Cloud Run min instances. 0 = scale to zero (cheap, cold starts). 1 = warm (faster first call)."
  default     = 0
}

variable "max_instances" {
  type    = number
  default = 3
}

variable "cpu" {
  type    = string
  default = "1"
}

variable "memory" {
  type    = string
  default = "2Gi" # 512Mi OOMs during gather (crawl + ADK + always-on Vertex hypothesize/leads planners)
}

variable "ingress" {
  type        = string
  description = "Cloud Run ingress. INGRESS_TRAFFIC_ALL lets local Claude reach it over the internet."
  default     = "INGRESS_TRAFFIC_ALL"
}

variable "allow_unauthenticated" {
  type        = bool
  description = "If true, grants run.invoker to allUsers; the app's A2A bearer token is then the only gate. If false, callers must present a Google identity token."
  default     = false
}

# ---------------------------------------------------------------------------
# knowledge-gathering bridge (see services.tf → module.kga_bridge)
# ---------------------------------------------------------------------------
variable "deploy_bridge" {
  type        = bool
  description = "Create the A2A->MCP bridge Cloud Run service."
  default     = true
}

variable "bridge_min_instances" {
  type        = number
  description = "Keep >=1: multi-turn refine holds session state in memory, so the loop must stay on a warm instance."
  default     = 1
}

variable "bridge_max_instances" {
  type        = number
  description = "1 pins all sessions to a single instance (simplest correct for in-memory refine state). Raise only with external session state."
  default     = 1
}

variable "bridge_cpu" {
  type    = string
  default = "1"
}

variable "bridge_memory" {
  type    = string
  default = "512Mi"
}

variable "bridge_allow_unauthenticated" {
  type        = bool
  description = "If true, grants run.invoker to allUsers. The bridge has NO app-level auth, so prefer false (private) and reach it with a Google ID token."
  default     = false
}

# ---------------------------------------------------------------------------
# test-plan-definition agent + bridge (see services.tf → module.tpd_agent / tpd_bridge)
# ---------------------------------------------------------------------------
variable "deploy_test_plan" {
  type        = bool
  description = "Create the test-plan-definition agent + its MCP bridge."
  default     = true
}

variable "tpd_service_name" {
  type        = string
  description = "test-plan-definition Cloud Run service name (A2A-only agent, ingress :8080)."
  default     = "test-plan-definition-agent-v2"
}

# ---------------------------------------------------------------------------
# test-evaluation agent + bridge (see services.tf → module.tev) — the pack-quality scorer.
# ---------------------------------------------------------------------------
variable "deploy_test_evaluation" {
  type        = bool
  description = "Create the test-evaluation agent + its MCP bridge."
  default     = true
}

variable "tev_service_name" {
  type        = string
  description = "test-evaluation Cloud Run service name (A2A-only agent, ingress :8080)."
  default     = "test-evaluation-agent-v2"
}

variable "tpd_llm_detail" {
  type        = bool
  description = "Enable the LLM-detailed implement (rich test-data + batched Claude steps). Slower (~minutes/run; the 600s timeouts cover it) but far richer output. Off = fast deterministic heuristics."
  default     = false
}

# ---------------------------------------------------------------------------
# admin_agent (see services.tf → module.admin) — the memory & history operator utility (NOT pipeline).
# Deterministic router, no LLM; needs GCS + DB, no Atlassian, no Vertex. wipe_all is destructive.
# ---------------------------------------------------------------------------
variable "deploy_admin" {
  type        = bool
  description = "Create the admin_agent Cloud Run service (memory & history operator utility)."
  default     = true
}

variable "admin_service_name" {
  type        = string
  description = "admin_agent Cloud Run service name (A2A-only utility agent, ingress :8080)."
  default     = "admin-agent-v2"
}

# --- Redis / Memorystore benchmark cache (default OFF — the cache is a no-op until enabled) ---
variable "deploy_redis" {
  type        = bool
  description = "Provision Memorystore Redis + a Serverless VPC connector and point TEV's benchmark cache at it (CACHE_BACKEND=redis). Off = benchmark cache is a no-op (NullCache)."
  default     = false
}

variable "redis_tier" {
  type        = string
  description = "Memorystore tier: BASIC (no HA) or STANDARD_HA."
  default     = "BASIC"
}

variable "redis_memory_gb" {
  type        = number
  description = "Memorystore capacity in GB."
  default     = 1
}

variable "redis_network" {
  type        = string
  description = "VPC network (name or self-link) for Memorystore + the Serverless VPC connector."
  default     = "default"
}

variable "vpc_connector_cidr" {
  type        = string
  description = "An unused /28 range for the Serverless VPC Access connector."
  default     = "10.8.0.0/28"
}

# ---------------------------------------------------------------------------
# Single MCP gateway (G2) — the one endpoint Claude connects to; fronts the 3 A2A agents.
# ---------------------------------------------------------------------------
variable "deploy_gateway" {
  type        = bool
  description = "Create the single mcp-gateway-v2 service (the one MCP endpoint Claude connects to)."
  default     = true
}

variable "gateway_service_name" {
  type        = string
  description = "Cloud Run service name for the single MCP gateway."
  default     = "mcp-gateway-v2"
}

# ---------------------------------------------------------------------------
# Cloud exploration tiers 5/6/7 (KGA) — config-driven, opt-in via config PRESENCE (no separate flag).
# Set `gcp_env_matrix` to a non-empty JSON map to turn the tiers ON; grant read access by listing the
# projects in `cloud_exploration_projects`. Both empty (the default) = tiers stay OFF.
# ---------------------------------------------------------------------------
variable "gcp_env_matrix" {
  type        = string
  description = "JSON for KGA_GCP_ENV_MATRIX — env -> {project, region, cluster, namespace}. Empty = cloud tiers off. See gcp-env-matrix.example.json."
  default     = ""
}

variable "cloud_exploration_projects" {
  type        = list(string)
  description = "Projects the KGA runtime SA may READ (viewer roles) for cloud tiers 5/6/7. Empty = no bindings created."
  default     = []
}
