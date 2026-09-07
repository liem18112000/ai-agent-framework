---
name: gcp-observability-metrics
description: >-
  Cloud Monitoring / metrics expert for the LUZ ops repo — the
  custom-metrics-stackdriver-adapter, Google Managed Prometheus PodMonitoring
  CRDs, and OpenTelemetry tracing toggles. Use when inspecting HPA metric
  sources, adding a /metrics scrape endpoint, enabling Managed Prometheus, or
  toggling distributed tracing for a service. Don't use for log-based metrics
  (see gcp-observability-logging), alert policies built on a metric (see
  gcp-observability-alerting), or GKE cluster/node config (see gcp-gke).
metadata:
  category: CloudObservabilityAndMonitoring
---

# Cloud Monitoring / Metrics — LUZ Ops

Metrics collection is **Google Managed Prometheus**, not Grafana (no Grafana
manifests exist anywhere in the repo). Dashboards are Cloud Monitoring only.

## Known resources in this repo

- **`custom-metrics-stackdriver-adapter`** — deployed via kustomize (not
  Terraform), one overlay per project:
  `luz_kubernetes/kubernetes-overlays/env-custom-metrics/custom-metrics-adapter/custom-metrics.yaml` (klara-nonprod),
  `env-prod-custom-metrics/custom-metrics-adapter/custom-metrics.yaml` (klara-prod),
  `env-performance-custom-metrics/custom-metrics-adapter/custom-metrics.yaml` (klara-performance).
  Runs in dedicated namespace `custom-metrics`, ServiceAccount
  `custom-metrics-stackdriver-adapter` bound via Workload Identity to
  `custom-metrics@<project>.iam.gserviceaccount.com`, registers
  `v1beta1/v1beta2.custom.metrics.k8s.io` and `v1beta1.external.metrics.k8s.io`
  APIServices, and grants the `horizontal-pod-autoscaler` SA in `kube-system`
  access via the `external-metrics-reader` ClusterRoleBinding.
  **Known gap**: it's wired correctly in all 3 clusters but **no HPA in the
  repo actually consumes a custom/external metric** — every
  `horizontal-pod-autoscaler.yaml` sampled uses `type: Resource` (CPU/memory)
  only. Treat it as provisioned-but-latent capacity, not proof metrics-based
  autoscaling is in use.
- **Managed Prometheus enablement**:
  `luz_kubernetes/cluster/gcp/manual_script/enable_managed_prometheus.sh` —
  idempotent `gcloud beta container clusters update --enable-managed-prometheus`.
- **`PodMonitoring` CRDs** (`monitoring.googleapis.com/v1`, the Managed
  Prometheus scrape-config resource) — widely used across
  `luz_kubernetes/kubernetes-overlays/env-{dev,test,prod,performance}/{luz-docs,luz-jsonstore,luz-pos,luz-storage-batch,luz-storage,luz-antivirus,luz-thumbnail,luz-webclient,luz-eletter*,luz-insurance}/pod-monitoring*.yaml`.
  Typical shape: scrape `port: metrics`, `path: /metrics/application` (Java
  apps) or `path: /metrics` (health-check sidecars), `interval: 10s`–`30s`.
  Some services inject a `metrics-proxy` sidecar (nginx, port 9090) via
  `patch-monitoring.json`/`patch-monitoring-batch.json` when the app doesn't
  natively expose a scrapeable endpoint.
- **Distributed tracing (OpenTelemetry, off by default)**:
  `luz_kubernetes/kubernetes/tracing/k8s.yaml` /`k8s-enabled.yaml` — ConfigMap
  `backend-tracing-javaagent` sets `OTEL_JAVAAGENT_ENABLED`. Toggle scripts:
  `luz_kubernetes/cluster/gcp/manual_script/tracing/turn_on_tracing.sh` /
  `turn_off_tracing.sh` (patch the ConfigMap + rolling-restart all deployments
  in the namespace except database/ingress/mongo/keycloak). Example baseline:
  `luz_kubernetes/terraform/luz-message-broker/main.tf:7` sets
  `OTEL_JAVAAGENT_ENABLED = "false"`.
- **Dashboards**: only Cloud Armor WAF has dashboards-as-JSON (Console-exported,
  not `google_monitoring_dashboard` Terraform):
  `luz_kubernetes/cluster/gcp/cloud_armor/dashboard/klara-{nonprod,prod}_KLARA - Cloud Armor WAF.json`.
  No other service has a dashboard checked into the repo.

## Common commands

```bash
# check Managed Prometheus status on a cluster
gcloud container clusters describe klara-nonprod --zone europe-west6-a --project klara-nonprod \
  --format="value(monitoringConfig.managedPrometheusConfig.enabled)"

# list PodMonitoring resources in a namespace
kubectl get podmonitoring -n dev

# check custom-metrics-adapter health
kubectl get pods -n custom-metrics
kubectl get apiservice v1beta1.custom.metrics.k8s.io -o yaml

# toggle tracing for a namespace (mirrors turn_on_tracing.sh)
kubectl get configmap backend-tracing-javaagent -n dev -o yaml

# query a custom/external metric an HPA could use
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/dev/pods/*/<metric-name>"
```

## Safety notes

`turn_on_tracing.sh`/`turn_off_tracing.sh` rolling-restart every deployment in
a namespace — never run these against a `prod` namespace without explicit
confirmation, since it causes a full rollout. Enabling Managed Prometheus on
a cluster is generally safe/idempotent but still confirm before running
against `klara-prod`. Read-only `get`/`describe`/`list` need no confirmation.

## Reference Directory

- `luz_kubernetes/kubernetes-overlays/env-*-custom-metrics/custom-metrics-adapter/custom-metrics.yaml`
- `luz_kubernetes/cluster/gcp/manual_script/enable_managed_prometheus.sh`
- `luz_kubernetes/kubernetes-overlays/env-*/*/pod-monitoring*.yaml`
- `luz_kubernetes/kubernetes/tracing/k8s.yaml`, `k8s-enabled.yaml`
- `luz_kubernetes/cluster/gcp/manual_script/tracing/{turn_on_tracing.sh,turn_off_tracing.sh}`
