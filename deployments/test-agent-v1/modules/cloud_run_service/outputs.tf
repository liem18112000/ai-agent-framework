output "uri" {
  description = "The service's HTTPS URL (null when create = false)."
  value       = var.create ? google_cloud_run_v2_service.this[0].uri : null
}

output "name" {
  value = var.create ? google_cloud_run_v2_service.this[0].name : null
}

output "location" {
  value = var.create ? google_cloud_run_v2_service.this[0].location : null
}
