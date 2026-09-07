---
name: gcp-observability-alerting
description: >-
  Cloud Monitoring alerting expert for the LUZ ops repo — the split between a
  small Terraform-managed alerting world and a much larger imperative
  gcloud+JSON-template world, plus notification-channel gaps. Use when
  creating, inspecting, or fixing an alert policy or notification channel, or
  investigating why an alert didn't page anyone. Don't use for the log-based
  metric an alert reads from (see gcp-observability-logging), Cloud Build
  Slack deployment notifications (unrelated to runtime alerting), or SLO
  burn-rate design (see gcp-observability-slos, which doesn't exist yet in
  this repo).
metadata:
  category: CloudObservabilityAndMonitoring
---

# Cloud Monitoring Alerting — LUZ Ops

**Two parallel alerting worlds coexist.** Know which one you're touching
before changing anything:

1. **Terraform-managed** (small, clean, only 3 files) — edits go through
   `terraform apply` and are idempotent/declarative.
2. **Imperative gcloud + JSON-template scripts** (large, legacy, most of the
   real alert coverage) — these `gcloud alpha monitoring policies create
   --policy-from-file=<json>`, are **create-if-absent**: re-running a script
   after editing its JSON template does **not** update the existing policy —
   you must delete the old policy first or edit it via Console/`gcloud
   alpha monitoring policies update`.

## Known resources in this repo

### Terraform world
- `luz_kubernetes_infra/terraform/common/security/cloud-armor/metrics-and-alerts.tf`
  — `cloud_armor_waf_denied_http_requests_count_alert` (count > 0 over 300s)
  and `..._rate_alert` (rate > 50 req/s over 60s), both `auto_close=604800s`
  (7d), notify `module.notification_channels.notification_channel_email_team_future`.
- `luz_kubernetes/terraform-infra/securemail/alerts.tf` —
  `zonemta_connectivity_alert`, `zonemta_no_public_ip_alert` (threshold 0,
  `auto_close=1800s`). **Notification channels are commented out** — TODO
  left in the file. Rich markdown runbooks embedded in `documentation` blocks.
- `luz_kubernetes_infra/terraform/common/monitoring/alerting/notification-channels/main.tf`
  — the only shared channel module. **Active channel**: `email_team_future`
  (`hcmc-future@axonactive.com`). A second channel (`email_toan_nguyen`) is
  commented out. No Slack/SMS/PagerDuty channel type exists in Terraform.

### Imperative world (`luz_kubernetes/cluster/gcp/manual_script/*_alerting/`)
Each family has a create script + per-env JSON policy template
(dev/test/performance/prod, sometimes swissdec):
- `ecp_log_alerting/` — creates notification channels on the fly
  (create-if-absent via `gcloud alpha monitoring channels list`) using
  `$NOTIFICATION_CHANNEL_EMAIL_1`/`_2`; policy
  `${LUZ_ENV}_ecp_log_subscribe_message_error`. **Has channels attached.**
- `ivy_license_alerting/` — `${LUZ_ENV}_ivy_license_expiry_{warning,critical}`.
  **Does NOT attach notification channels** — script prints a manual TODO to
  add them via Console.
- `oneapi_alerting/` — email-response, OOM, pod-restart-loop, and Pub/Sub
  alert scripts, each per-env. OOM example matches 19 named apps
  (`luz-eletter`, `luz-docs-view-controller-batch`, ..., `luz-store`) for
  `java.lang.OutOfMemoryError` in logs, `notificationRateLimit.period=1800s`.
  **Channel attachment inconsistent per script** — verify before assuming.
- `swisssign_signing_failure_alerting/`, `luz_crypto_alerting/` (cert expiry +
  health-down), `snapshot_solution_alerting/`,
  `temporary_document_storage_error_alerting/`, `force_onboarding_alerting/`,
  `document_failed_to_store_alerting/` — same pattern.
- Legacy/placeholder templates (do not use as-is):
  `luz_kubernetes/kubernetes/luz-docs/alert/alert_luz_docs.json` (blank
  filter/displayName), `luz_kubernetes/kubernetes/luz-store/alert/alert_luz_store_log_based.json`,
  `luz_kubernetes/kubernetes/luz-jsonstore/alert-do-not-use/alert_luz_jsonstore_promql_based.json`
  — directory literally named "alert-do-not-use".
- Cloud Armor also has separate imperative deploy scripts parallel to (and
  possibly overlapping/superseded by) the Terraform ones above:
  `luz_kubernetes/cluster/gcp/cloud_armor/deploy_cloud_armor_*_metric_and_alerting_regional.sh`.

### Notification emails by environment (used by the create scripts)
`luz_kubernetes/configuration/env.sh:82` `CLOUD_ARMOR_NOTIFICATION_CHANNEL_EMAIL_1='ops@klara.ch'`;
per-env pairs in `env-{test,dev,performance,prod}/env.sh` (e.g. prod:
`invisible@klara.ch`, `sebastian.metzger@klara.ch`).

### NOT alerting (common confusion)
The `slack-webhook-url` secret and `luz_kubernetes/utilities/notify_deployment_status.sh`
are **Cloud Build deployment success/failure notifications**, not runtime
monitoring alerts — they're triggered by the CI pipeline, not by a
`google_monitoring_alert_policy`. Don't conflate the two when debugging "why
didn't I get paged."

## Common commands

```bash
# list alert policies
gcloud alpha monitoring policies list --project klara-nonprod

# check if a policy has notification channels attached
gcloud alpha monitoring policies describe <policy-id> --project klara-prod \
  --format="value(notificationChannels)"

# list notification channels
gcloud alpha monitoring channels list --project klara-infra

# re-create/update an imperative policy: delete first, then re-run the script
gcloud alpha monitoring policies delete <policy-id> --project klara-nonprod
bash luz_kubernetes/cluster/gcp/manual_script/ivy_license_alerting/create_ivy_license_alerting.sh
```

## Safety notes

Never delete or disable an alert policy in `klara-prod` without explicit
confirmation naming the exact policy — especially the `ecp_log`, `oneapi`,
and Cloud Armor families, which are the main paging coverage in prod. When
asked to "fix" an alert missing notification channels (a known gap for
`ivy_license_alerting` and possibly others), confirm the intended channel(s)
with the user before attaching — don't guess at who should be paged.
Read-only `list`/`describe` need no confirmation.

## Reference Directory

- `luz_kubernetes_infra/terraform/common/security/cloud-armor/metrics-and-alerts.tf`
- `luz_kubernetes/terraform-infra/securemail/alerts.tf`
- `luz_kubernetes_infra/terraform/common/monitoring/alerting/notification-channels/main.tf`
- `luz_kubernetes/cluster/gcp/manual_script/*_alerting/` — all imperative alert families.
- `luz_kubernetes/utilities/notify_deployment_status.sh` — Slack CI notifications (not runtime alerting).
