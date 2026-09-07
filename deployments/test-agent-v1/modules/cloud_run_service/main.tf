# ===========================================================================
# Reusable Cloud Run v2 service for the Testing-Agent stack.
#
# Renders one or more containers. A single-container service is just a one-element
# `containers` list; a co-located agent+bridge service is two containers — the bridge
# as the ingress (ingress_port set) and the agent as a localhost sidecar. Probe timings
# are identical everywhere, so they are baked in; only the probe kind (http path vs tcp
# port), its target port, and liveness are per-container inputs.
# ===========================================================================

resource "google_cloud_run_v2_service" "this" {
  count = var.create ? 1 : 0

  name                = var.name
  location            = var.location
  ingress             = var.ingress
  deletion_protection = var.deletion_protection

  template {
    service_account  = var.service_account_email
    session_affinity = var.session_affinity
    timeout          = var.timeout

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    # Cloud SQL Auth proxy socket (durable A2A task store), mounted by containers that opt in.
    dynamic "volumes" {
      for_each = var.cloudsql_instance == "" ? [] : [1]
      content {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [var.cloudsql_instance]
        }
      }
    }

    dynamic "containers" {
      for_each = { for c in var.containers : c.name => c }
      content {
        name       = containers.value.name
        image      = containers.value.image
        command    = containers.value.command
        args       = containers.value.args
        depends_on = containers.value.depends_on_containers

        # Exactly one container (the ingress) declares a port.
        dynamic "ports" {
          for_each = containers.value.ingress_port == null ? [] : [1]
          content {
            container_port = containers.value.ingress_port
          }
        }

        resources {
          limits = {
            cpu    = containers.value.cpu
            memory = containers.value.memory
          }
          cpu_idle          = containers.value.cpu_idle
          startup_cpu_boost = containers.value.startup_cpu_boost
        }

        dynamic "volume_mounts" {
          for_each = containers.value.mount_cloudsql ? [1] : []
          content {
            name       = "cloudsql"
            mount_path = "/cloudsql"
          }
        }

        dynamic "env" {
          for_each = containers.value.env
          content {
            name  = env.value.name
            value = env.value.secret == null ? env.value.value : null
            dynamic "value_source" {
              for_each = env.value.secret == null ? [] : [1]
              content {
                secret_key_ref {
                  secret  = env.value.secret
                  version = env.value.version
                }
              }
            }
          }
        }

        startup_probe {
          dynamic "http_get" {
            for_each = containers.value.startup_probe_http_path == null ? [] : [1]
            content {
              path = containers.value.startup_probe_http_path
              port = containers.value.probe_port
            }
          }
          dynamic "tcp_socket" {
            for_each = containers.value.startup_probe_tcp_port == null ? [] : [1]
            content {
              port = containers.value.startup_probe_tcp_port
            }
          }
          initial_delay_seconds = 2
          timeout_seconds       = 3
          period_seconds        = 5
          failure_threshold     = 10
        }

        dynamic "liveness_probe" {
          for_each = containers.value.liveness_probe_http_path == null ? [] : [1]
          content {
            http_get {
              path = containers.value.liveness_probe_http_path
              port = containers.value.probe_port
            }
            period_seconds    = 30
            timeout_seconds   = 3
            failure_threshold = 3
          }
        }
      }
    }
  }
}

# Optional public invoker — app-level bearer is then the only gate.
resource "google_cloud_run_v2_service_iam_member" "invoker" {
  count    = var.create && var.allow_unauthenticated ? 1 : 0
  name     = google_cloud_run_v2_service.this[0].name
  location = google_cloud_run_v2_service.this[0].location
  role     = "roles/run.invoker"
  member   = "allUsers"
}
