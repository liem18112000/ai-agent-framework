---
name: gcp-observability-errors
description: >-
  Error-tracking expert for the LUZ ops repo — the single Sentry integration
  (Tuwunel/Matrix communities service) and the fact that Cloud Error Reporting
  is NOT used anywhere else in this repo. Use when investigating exception
  tracking for the communities/Matrix service, or asked to add error tracking
  to another service. Don't use for log-based error alert policies on
  core LUZ services like oneapi OOM/error alerts (see
  gcp-observability-alerting) or general Cloud Logging (see
  gcp-observability-logging).
metadata:
  category: CloudObservabilityAndMonitoring
---

# Error Tracking — LUZ Ops

**No Google Cloud Error Reporting integration exists anywhere in this repo**
(no client libraries, no `clouderrorreporting` API enablement). Core LUZ/klara
application services (luz-corapi, luz-docs, luz-eletter, etc.) track errors
via **log-based metrics + alert policies** instead — see
`gcp-observability-alerting` (e.g. the `oneapi_alerting` OOM/error-rate
scripts, `alert_luz_docs.json`'s error-ratio metric).

## Known resources in this repo

- **Sentry — the one real exception-tracking integration**, scoped to the
  Tuwunel/Matrix homeserver (`communities` stack) only:
  `luz_kubernetes/terraform-infra/communities/files/tuwunel.toml:453-462`
  and the templated `tuwunel.toml.j2:454-464`:
  ```
  sentry = true
  sentry_endpoint = "https://a763d5b1488a46364f3c23578dae78c1@o4509038810038272.ingest.de.sentry.io/4509038812790864"
  sentry_send_server_name = true
  sentry_attach_stacktrace = false
  sentry_send_panic = true
  sentry_send_error = true
  sentry_filter = "info"
  sentry_traces_sample_rate = 0.15
  ```
  This is a checked-in Sentry DSN (public/client key, standard for Sentry)
  with 15% trace sampling. It is **not** used by any other service — do not
  assume Sentry coverage exists for luz-corapi, luz-docs, or any other
  klara/LUZ application.
- No Rollbar, Bugsnag, or other exception-tracking library found anywhere
  else in `luz_kubernetes*`/`luz_dockerfiles`.

## Common commands

```bash
# find current Sentry config for communities
grep -n "sentry" luz_kubernetes/terraform-infra/communities/files/tuwunel.toml.j2

# check error-rate alert coverage for a core service instead (no Sentry there)
grep -rl "OutOfMemoryError\|error_ratio\|ERROR" luz_kubernetes/cluster/gcp/manual_script/oneapi_alerting/
```

## Safety notes

The Sentry DSN in `tuwunel.toml.j2` is a public/client key by Sentry's own
design (safe to be in a public SDK payload), but treat the `sentry_endpoint`
value itself as configuration to change carefully — swapping it without
confirmation would silently redirect crash reports to a different Sentry
project. Don't add a new Sentry DSN to any other service without explicit
user direction; this repo's convention for core services is log-based
alerting, not Sentry.

## Reference Directory

- `luz_kubernetes/terraform-infra/communities/files/tuwunel.toml`, `tuwunel.toml.j2`
- `luz_kubernetes/cluster/gcp/manual_script/oneapi_alerting/` — the log-based
  error/OOM alerting pattern used instead of Error Reporting for core services.
