# --- Memorystore Redis (shared benchmark cache) + Serverless VPC connector for Cloud Run egress ---
# Gated by var.deploy_redis (default false) — off leaves every existing deploy untouched, and the
# TEV benchmark cache stays a no-op (CACHE_BACKEND unset → NullCache). On: TEV points at this Redis.
# Memorystore has a private IP inside the VPC, so Cloud Run needs a Serverless VPC Access connector
# to reach it (that's why the TEV service gets vpc_connector when deploy_redis is on).

resource "google_project_service" "redis_apis" {
  for_each           = var.deploy_redis ? toset(["redis.googleapis.com", "vpcaccess.googleapis.com"]) : []
  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

resource "google_redis_instance" "cache" {
  count              = var.deploy_redis ? 1 : 0
  name               = "${var.name_prefix}-cache"
  project            = var.project_id
  region             = var.region
  tier               = var.redis_tier
  memory_size_gb     = var.redis_memory_gb
  redis_version      = "REDIS_7_0"
  authorized_network = var.redis_network
  depends_on         = [google_project_service.redis_apis]
}

resource "google_vpc_access_connector" "redis" {
  count         = var.deploy_redis ? 1 : 0
  name          = "${var.name_prefix}-cache-conn"
  project       = var.project_id
  region        = var.region
  network       = var.redis_network
  ip_cidr_range = var.vpc_connector_cidr
  # The connector API requires instance sizing (else create fails: "must specify either
  # max_throughput or max_instances"). 2/3 are the minimums for the default e2-micro machine type.
  min_instances = 2
  max_instances = 3
  depends_on    = [google_project_service.redis_apis]
}
