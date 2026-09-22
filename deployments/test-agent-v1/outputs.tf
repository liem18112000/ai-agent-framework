# The agents are sidecars now — reachable only on localhost inside their service, so there is
# no public agent URL. Claude connects to the bridge (MCP) endpoints below.

output "bridge_url" {
  description = "knowledge-gathering MCP endpoint. Register: claude mcp add --transport http knowledge-gathering <bridge_url>"
  value       = var.deploy_bridge ? "${module.kga.uri}/mcp" : null
}

output "tpd_bridge_url" {
  description = "test-plan-definition MCP endpoint. Register: claude mcp add --transport http test-plan-definition <tpd_bridge_url>"
  value       = var.deploy_test_plan ? "${module.tpd.uri}/mcp" : null
}

output "tev_bridge_url" {
  description = "test-evaluation MCP endpoint. Register: claude mcp add --transport http test-evaluation <tev_bridge_url>"
  value       = var.deploy_test_evaluation ? "${module.tev.uri}/mcp" : null
}

output "memory_bucket" {
  description = "GCS memory-bank bucket."
  value       = google_storage_bucket.memory.name
}

output "runtime_service_account" {
  description = "The single SA shared by both containers of both services."
  value       = google_service_account.kga.email
}

output "artifact_repo" {
  description = "Docker repo to push the image to."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "secret_ids" {
  description = "Add a version to each before the service can start."
  value = {
    atlassian_api_token = google_secret_manager_secret.atlassian_token.secret_id
    a2a_bearer_token    = google_secret_manager_secret.a2a_bearer.secret_id
  }
}

output "cloudsql_connection_name" {
  description = "Cloud SQL instance connection name (PROJECT:REGION:INSTANCE) the agent sidecars mount as the task store."
  value       = var.deploy_cloudsql ? google_sql_database_instance.taskstore[0].connection_name : null
}
