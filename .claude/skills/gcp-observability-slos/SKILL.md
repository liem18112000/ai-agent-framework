---
name: gcp-observability-slos
description: >-
  SLO/uptime expert for the LUZ ops repo — there is no GCP-native SLO or
  uptime-check tooling in use; the only synthetic monitoring is a custom
  Puppeteer CronJob. Use when investigating uptime/availability monitoring for
  klara, or asked to design/add a formal SLO. Don't use for the alert
  policies a synthetic check's log output could feed (see
  gcp-observability-alerting) or general Cloud Monitoring metrics (see
  gcp-observability-metrics).
metadata:
  category: CloudObservabilityAndMonitoring
---

# SLOs / Uptime — LUZ Ops

**No `google_monitoring_slo`, no `google_monitoring_uptime_check_config`, no
SLI/SLO definition files, and no error-budget policy exist anywhere in this
repo.** If asked to report "the SLO for X," the honest answer is that none is
formally defined — the closest thing is the synthetic uptime CronJob below.

## Known resources in this repo

- **`klara-uptime-monitoring` CronJob** —
  `luz_kubernetes/kubernetes/cronjob/klara-uptime-monitoring/klara-uptime-monitoring.yaml`:
  schedule `*/10 * * * *` (every 10 min), `timeZone: Europe/Zurich`,
  `concurrencyPolicy: Forbid`, image `puppeteer:fd9ee09`. Deployed per-env via
  `luz_kubernetes/kubernetes-overlays/env-{dev,dev-vn,dev-staging,performance,prod,swissdec,test}/cronjob/klara-uptime-monitoring/`,
  each with its own SOPS-encrypted credential secret.
- **The script**:
  `luz_kubernetes/kubernetes/cronjob/klara-uptime-monitoring/klara-uptime-monitoring.js`
  — Puppeteer login to `https://app.klara.ch`, clicks through
  Accounting/Company/e-Archive/Monitoring/User-Management/Dashboard, measures
  per-step response time against `RESPONSE_TIME_LIMIT` (default 10000ms).
  Emits sentinel log lines: `KLARA_REALISTIC_UPTIME_STABLE`,
  `KLARA_REALISTIC_UPTIME_UNSTABLE`,
  `KLARA_REALISTIC_UPTIME_UNSTABLE_LONG_RESPONSE`,
  `KLARA_REALISTIC_UPTIME_CLICK_ERROR`, `KLARA_REALISTIC_UPTIME_BROWSER_ERROR`,
  `KLARA_REALISTIC_UPTIME_RESPONSE_TIME - <seconds> - <url>`. **No downstream
  log-based metric or alert policy referencing these exact strings was found**
  — the synthetic check runs, but its alerting wiring (if any) wasn't
  located; verify before assuming these pages anyone.
- Provisioning: `luz_kubernetes/sops/scripts/klara-uptime-monitoring-create-env-secret.sh`.
- **Security hygiene item to flag, not silently fix**:
  `klara-uptime-monitoring.js:6-13` hardcodes fallback default credentials
  (`KLARA_USERNAME = "ops@klara.ch"`, a plaintext default password) as JS
  default parameter values, even though the real per-env credential is meant
  to come from the SOPS-encrypted secret via `envFrom.secretRef`. Surface
  this to the user if it comes up; don't change it without being asked.

## Common commands

```bash
# check recent CronJob runs
kubectl get cronjob klara-uptime-monitoring -n dev
kubectl get jobs -n dev -l job-name=klara-uptime-monitoring* --sort-by=.metadata.creationTimestamp

# tail the most recent run's logs for the sentinel markers
kubectl logs -n prod -l job-name=$(kubectl get jobs -n prod -o jsonpath='{.items[-1:].metadata.name}')

# search for whether anything downstream consumes the sentinel log strings
grep -rl "KLARA_REALISTIC_UPTIME" luz_kubernetes/cluster/gcp/manual_script/ luz_kubernetes_infra/terraform/
```

## Safety notes

If the user wants a real SLO (e.g. "99.9% of logins under 2s"), this needs to
be built net-new — propose a `google_monitoring_slo` + uptime check or a
log-based metric off the existing sentinel strings, and confirm the target
and error-budget window with the user before creating anything, since SLOs
often gate release/rollback policy elsewhere. Never change
`RESPONSE_TIME_LIMIT` or the CronJob schedule in `prod` without confirmation.

## Reference Directory

- `luz_kubernetes/kubernetes/cronjob/klara-uptime-monitoring/klara-uptime-monitoring.yaml`
- `luz_kubernetes/kubernetes/cronjob/klara-uptime-monitoring/klara-uptime-monitoring.js`
- `luz_kubernetes/kubernetes-overlays/env-*/cronjob/klara-uptime-monitoring/`
- `luz_kubernetes/sops/scripts/klara-uptime-monitoring-create-env-secret.sh`
