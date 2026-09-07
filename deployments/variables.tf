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

variable "name_prefix" {
  type        = string
  description = "Prefix for named resources."
  default     = "kga"
}

variable "service_name" {
  type        = string
  description = "knowledge-gathering Cloud Run service name (bridge ingress + agent sidecar)."
  default     = "knowledge-gathering-agent"
}

variable "service_account_id" {
  type        = string
  description = "Runtime service account id (account_id part)."
  default     = "kga-runtime"
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
  default = "512Mi"
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
  description = "test-plan-definition Cloud Run service name (bridge ingress + agent sidecar)."
  default     = "test-plan-definition-agent"
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
  description = "test-evaluation Cloud Run service name (bridge ingress + agent sidecar)."
  default     = "test-evaluation-agent"
}

variable "tpd_llm_detail" {
  type        = bool
  description = "Enable the LLM-detailed implement (rich test-data + batched Claude steps). Slower (~minutes/run; the 600s timeouts cover it) but far richer output. Off = fast deterministic heuristics."
  default     = false
}

variable "kga_self_explore" {
  type        = bool
  description = "Enable the KGA self-exploration stack G2-G5 (KGA_LLM_HYPOTHESIZE + KGA_FOLLOW_WEB + KGA_LLM_LEADS + KGA_EXPLORE_LOOP). Turns the single pre-crawl fan-out into a bounded, resumable multi-round explore loop with optional LLM-focused search terms/leads and external-web following. Off = single fan-out, byte-for-byte unchanged. Bounds are conservative (3 rounds / 300s total, under the 600s timeout)."
  default     = false
}
