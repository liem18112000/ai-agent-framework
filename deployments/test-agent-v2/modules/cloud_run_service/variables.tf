variable "create" {
  type        = bool
  description = "Toggle the whole service on/off (drives count)."
  default     = true
}

variable "name" {
  type        = string
  description = "Cloud Run service name."
}

variable "location" {
  type = string
}

variable "ingress" {
  type    = string
  default = "INGRESS_TRAFFIC_ALL"
}

variable "deletion_protection" {
  type    = bool
  default = false
}

variable "service_account_email" {
  type        = string
  description = "Runtime SA email shared by ALL containers in the service. May be null when create = false."
  default     = null
}

variable "timeout" {
  type        = string
  description = "Request timeout, e.g. \"600s\". null = Cloud Run default (300s)."
  default     = null
}

variable "session_affinity" {
  type        = bool
  description = "Pin a client to one instance — needed when a container holds in-memory session state."
  default     = false
}

variable "min_instances" {
  type = number
}

variable "max_instances" {
  type = number
}

variable "cloudsql_instance" {
  type        = string
  description = "Cloud SQL connection name for a service-level volume named 'cloudsql'. \"\" = no Cloud SQL volume. Individual containers opt into the mount via mount_cloudsql."
  default     = ""
}

variable "allow_unauthenticated" {
  type        = bool
  description = "Grant run.invoker to allUsers (the app-level bearer becomes the only gate)."
  default     = false
}

variable "vpc_connector" {
  type        = string
  description = "Serverless VPC Access connector id for reaching private services (e.g. Memorystore Redis). \"\" = no VPC egress."
  default     = ""
}

variable "containers" {
  description = <<-EOT
    One or more containers. Exactly one must set ingress_port (it receives external traffic and
    the Cloud Run $PORT); the rest are sidecars reachable on localhost. Each container's env is an
    ordered list of literal {name,value} or secret {name,secret[,version]} entries.
  EOT
  type = list(object({
    name              = string
    image             = string
    command           = optional(list(string))
    args              = optional(list(string))
    ingress_port      = optional(number) # set on the single ingress container only
    cpu               = optional(string, "1")
    memory            = optional(string, "512Mi")
    cpu_idle          = optional(bool)
    startup_cpu_boost = optional(bool)
    mount_cloudsql    = optional(bool, false)
    env = optional(list(object({
      name    = string
      value   = optional(string)
      secret  = optional(string)
      version = optional(string, "latest")
    })), [])
    startup_probe_http_path  = optional(string)
    startup_probe_tcp_port   = optional(number)
    probe_port               = optional(number) # port the probes target (defaults to the container/ingress port)
    liveness_probe_http_path = optional(string)
    depends_on_containers    = optional(list(string), [])
  }))
}
