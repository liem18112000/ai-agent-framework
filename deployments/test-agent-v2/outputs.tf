# Claude connects to the SINGLE gateway (MCP). The agents are A2A-only (reached by the gateway).

output "gateway_url" {
  description = "The one MCP endpoint. Register: claude mcp add --transport http testing-agent <gateway_url>"
  value       = var.deploy_gateway ? "${module.gateway.uri}/mcp" : null
}

output "kga_a2a_url" {
  description = "knowledge-gathering A2A base URL (the gateway's KGA_A2A_URL)."
  value       = var.deploy_bridge ? module.kga.uri : null
}

output "tpd_a2a_url" {
  description = "test-plan-definition A2A base URL (the gateway's TPD_A2A_URL)."
  value       = var.deploy_test_plan ? module.tpd.uri : null
}

output "tev_a2a_url" {
  description = "test-evaluation A2A base URL (the gateway's TEV_A2A_URL)."
  value       = var.deploy_test_evaluation ? module.tev.uri : null
}

output "memory_bucket" {
  description = "GCS memory-bank bucket."
  value       = google_storage_bucket.memory.name
}

output "runtime_service_account" {
  description = "The single SA shared by the gateway + all agent containers."
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
  description = "Cloud SQL instance connection name (PROJECT:REGION:INSTANCE) the agents mount as the task store."
  value       = var.deploy_cloudsql ? google_sql_database_instance.taskstore[0].connection_name : null
}
