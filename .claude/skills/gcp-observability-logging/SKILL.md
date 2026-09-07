---
name: gcp-observability-logging
description: >-
  Cloud Logging expert for the LUZ ops repo — log sinks/routers, long-retention
  buckets, and log-based metrics, all provisioned imperatively via gcloud
  scripts (no Terraform sinks exist). Use when inspecting or creating a log
  sink, long-retention log bucket, or log-based metric, or tracing a
  container's logs to their sink bucket. Don't use for alert policies built on
  top of a log-based metric (see gcp-observability-alerting), Cloud Monitoring
  custom metrics (see gcp-observability-metrics), or GKE workload logs in
  general (see gcp-gke).
metadata:
  category: CloudObservabilityAndMonitoring
---

# Cloud Logging — LUZ Ops

Every log sink in this repo is **provisioned imperatively via `gcloud`,
never Terraform** — there is no `google_logging_project_sink` resource
anywhere. GKE relies on the built-in Cloud Logging agent for container
stdout/stderr; no fluentd/fluentbit config exists.

## Known resources in this repo

- **Generic per-environment sink logic**:
  `luz_kubernetes/cluster/gcp/create_environment.sh:256-296`. For each
  container name listed in `$MODULES_NEED_TO_STORE_LOG_LONGER` it creates a
  GCS bucket `<module>-sink-logs` (STANDARD class, region
  `$LUZ_GCP_STORAGE_REGION`, `--retention=$LONG_BUCKET_RETENTION_PERIOD`) and
  a sink `<module>-log-router` → that bucket, filtered to
  `resource.type=k8s_container AND resource.labels.project_id=$LUZ_GCP_PROJECT_ID
  AND resource.labels.namespace_name=$LUZ_ENV AND resource.labels.container_name=<module>`,
  then grants the sink's writer identity `OWNER` ACL on the bucket.
- **Long-retention module lists per env** (`luz_kubernetes/configuration/env-*/env.sh`):
  dev/dev-vn/dev-staging/test/swissdec = `"luz-corapi luz-keyvaluestore luz-suva"`;
  performance = `"luz-corapi luz-keyvaluestore"` (no luz-suva); prod =
  `"prod-luz-corapi prod-luz-keyvaluestore prod-luz-suva"` (prod-prefixed).
- **One-off retrofit script**:
  `luz_kubernetes/cluster/gcp/manual_script/create_luz_suva_bucket_sink_logs.sh`
  — same bucket/sink naming, hardcoded `LONG_BUCKET_RETENTION_PERIOD=200d`,
  scoped to `*luz-suva*` only, meant to run once for environments predating
  the generic logic.
- **Log-based metrics** (`google_logging_metric`, the only Terraform logging
  resource type used):
  - `luz_kubernetes_infra/terraform/common/security/cloud-armor/metrics-and-alerts.tf:7-20`
    — `cloud_armor_waf_denied_http_requests_count` (filters out `.DS_Store`,
    `.env`, `.git`, `.php`, `.htaccess`, `passwd`, and bot user-agents
    `semrushbot|ahrefsbot|zgrab`).
  - `luz_kubernetes/terraform-infra/securemail/alerts.tf:1-16,72-88` —
    `zonemta_ping_failures` and `zonemta_no_public_ip`, both matching
    `resource.labels.pod_name=~"epost-zone-mta-.*"`.
- **App-specific Cloud Logging**: POS Android app credentials
  (`luz_kubernetes/kubernetes-overlays/env-*/luz-pos/posapp-android-google-cloud-logging.sops.yaml`,
  provisioned by `luz_kubernetes/sops/scripts/posapp-android-google-cloud-logging.sh`).

## Common commands

```bash
# read logs for a container in a namespace
gcloud logging read \
  'resource.type=k8s_container AND resource.labels.namespace_name=dev AND resource.labels.container_name=luz-corapi' \
  --project=klara-nonprod --limit=50

# list existing sinks (before creating a new one)
gcloud logging sinks list --project=klara-nonprod

# create a long-retention sink for a new module (mirrors create_environment.sh)
gcloud logging sinks create <module>-log-router \
  storage.googleapis.com/<module>-sink-logs \
  --project=klara-nonprod \
  --log-filter='resource.type=k8s_container AND resource.labels.project_id=klara-nonprod AND resource.labels.namespace_name=dev AND resource.labels.container_name=<module>'

# list log-based metrics
gcloud logging metrics list --project=klara-infra
```

## Safety notes

Sink creation is create-if-absent in the scripts — re-running
`create_environment.sh` or the one-off `create_luz_suva_bucket_sink_logs.sh`
against an environment that already has the sink/bucket may error or no-op;
check `gcloud logging sinks list` / `gcloud storage buckets list` first.
Never delete a `*-sink-logs` bucket or its sink against `klara-prod` without
explicit confirmation — these are long-retention compliance/audit logs.
Read-only `logging read`/`sinks list`/`metrics list` need no confirmation.

## Reference Directory

- `luz_kubernetes/cluster/gcp/create_environment.sh:256-296` — generic sink provisioning.
- `luz_kubernetes/cluster/gcp/manual_script/create_luz_suva_bucket_sink_logs.sh`
- `luz_kubernetes/configuration/env-*/env.sh` — `MODULES_NEED_TO_STORE_LOG_LONGER` per env.
- `luz_kubernetes_infra/terraform/common/security/cloud-armor/metrics-and-alerts.tf`
- `luz_kubernetes/terraform-infra/securemail/alerts.tf`
