---
name: gcp-gcs
description: >-
  Cloud Storage (GCS) expert for the LUZ ops repo — bucket naming, the
  Terraform state bucket, and the manual gcloud provisioning scripts (buckets
  here are NOT Terraform-managed). Use when inspecting, creating, or granting
  access to a GCS bucket, or investigating Terraform state or DB backup
  storage. Don't use for Secret Manager (see gcp-secretmanager) or IAM role
  design alone (see gcp-iam).
metadata:
  category: Storage
---

# GCS — LUZ Ops

Buckets are provisioned mainly via **manual gcloud shell scripts**, not
Terraform — no `google_storage_bucket` resource exists in the repo's
Terraform outside of the state backend itself.

## Known buckets

- `luz-terraform` — Terraform state bucket, prefix `state`, used by
  `luz_kubernetes/terraform/main.tf` (Cloud Run stack) and referenced (prefix
  `security/<env>`) by the Cloud Armor Terraform under
  `luz_kubernetes/cluster/gcp/cloud_armor/terraform/cloud-armor/`.
- `epost-${LUZ_ENV}-iletter-media` — media storage,
  `luz_kubernetes/configuration/env.sh:30`.
- `klara-${LUZ_ENV_SHORT}-db-backup-${LUZ_ENV_UUID}` — DB backups,
  `luz_kubernetes/configuration/env.sh:34`.
- `${LUZ_GCP_PROJECT_ID}-k8s-backups` — cluster backups,
  `luz_kubernetes/configuration/env.sh:62`.

Manual provisioning scripts (`luz_kubernetes/cluster/gcp/manual_script/`):
`create_service_account_and_gcs_bucket_for_polaris_knowledge.sh`,
`prepare_iletter_gcs.sh`,
`create_service_account_and_gcs_bucket_for_luz_undeliverable.sh`,
`create_service_account_and_gcs_bucket_for_luztenant_service.sh`,
`create_luz_suva_bucket_sink_logs.sh`,
`create_service_account_and_gcs_bucket_for_luz_storage.sh`,
`create_luz_clamav_bucket_and_service_account.sh`,
`create_bucket_for_indiv_login_tracking.sh`,
`create_cluster_backup_requirements.sh`,
`add_storage_admin_role_for_earchive_storage.sh`.

## Common commands

```bash
# list buckets in a project
gcloud storage buckets list --project=klara-nonprod

# describe a bucket (IAM, lifecycle, versioning)
gcloud storage buckets describe gs://klara-nonprod-k8s-backups

# check who has access
gcloud storage buckets get-iam-policy gs://luz-terraform

# safe read of terraform state (never edit directly)
gcloud storage cat gs://luz-terraform/state/<workspace>/default.tfstate | head -50
```

## Safety notes

`luz-terraform` holds Terraform state for every Cloud Run workspace — never
delete objects in it, never run `gcloud storage rm` against it, and treat any
edit to state as requiring explicit user confirmation (prefer `terraform
state` subcommands over touching the GCS objects directly). DB-backup buckets
(`klara-*-db-backup-*`) are the last line of defense for prod data — read-only
access unless the user explicitly asks to prune old backups.

## Reference Directory

- `luz_kubernetes/configuration/env.sh` — bucket naming source of truth.
- `luz_kubernetes/cluster/gcp/manual_script/` — all bucket-provisioning scripts.
- `luz_kubernetes/terraform/main.tf` — state backend config.
