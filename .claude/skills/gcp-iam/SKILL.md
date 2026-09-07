---
name: gcp-iam
description: >-
  IAM expert for the LUZ ops repo — service account naming, Workload Identity
  bindings, Cloud Build service agents, and IAM role grants across
  klara-nonprod/klara-prod/klara-performance/klara-infra. Use when creating or
  auditing service accounts, granting roles, wiring Workload Identity for a
  GKE workload, or investigating who-can-access-what. Don't use for GCS bucket
  ACLs (see gcp-gcs), Secret Manager accessor bindings alone (see
  gcp-secretmanager), or VPC firewall rules (see gcp-network).
metadata:
  category: Security
---

# GCP IAM — LUZ Ops

Service-account and Workload Identity conventions across the LUZ GCP estate, as
actually implemented in `luz_kubernetes`, `luz_kubernetes_infra`, and their
Terraform.

## Environments

| Project | Purpose |
|---|---|
| `klara-nonprod` | dev / dev-vn / dev-staging / test / swissdec |
| `klara-prod` | production |
| `klara-performance` | load/perf testing |
| `klara-infra` | shared DevOps: Cloud Build, Artifact Registry, devportal |

Cloud Build project number: `518364204428` (klara-infra). Region europe-west6
everywhere except dev-vn (asia-southeast1).

## Known resources in this repo

**Naming convention** (`luz_kubernetes/configuration/env.sh`):
- `klara-<env>-db-backup`, `klara-<env>-db-backup-reader`, `klara-<env>-deployer`,
  `klara-<env>-pubsub` — all `@<project>.iam.gserviceaccount.com`.
- `<GCP_PROJECT_ID>-k8s-backups` — cluster backup SA/bucket pairing.

**Workload Identity** — pool is always `<project>.svc.id.goog`, set in every
`gke.tf` (e.g. `luz_kubernetes/terraform-infra/tuwunel/gke.tf`,
`securemail-milter/gke.tf`, `_modules/simple-vpc-cluster/modules/cluster/gke.tf`).
Known GKE ServiceAccount → GSA bindings (`iam.gke.io/gcp-service-account`
annotation):
- `custom-metrics@<klara-nonprod|klara-performance|klara-prod>.iam.gserviceaccount.com`
  — `custom-metrics-adapter/custom-metrics.yaml`
- `polaris-llm-gateway-sa@klara-nonprod.iam.gserviceaccount.com` — env-dev,
  env-dev-vn `polaris-llm-gateway/k8s.yaml`
- `alloydb-proxy-sa@<project>.iam.gserviceaccount.com` (project varies per
  overlay) — `luz-alloydb/auth-proxy.yaml` across overlays
- **Tech debt**: `secmail-adm@PLACEHOLDER_PROJECT.iam.gserviceaccount.com` in
  `luz_kubernetes/kubernetes/luz-secure-mail-adm/serviceaccount.yaml:8` is an
  unresolved placeholder — flag it, don't assume a real project.

**Terraform-managed SAs**:
- `luz_kubernetes/terraform/common-cloudrun-resources/base-resources/service-account/main.tf`
  — generic Cloud Run `common-service-account`.
- `luz_kubernetes/terraform/common-cloudrun-resources/eventarc-pubsub-gke/main.tf`
  — Eventarc SA, `roles/eventarc.eventReceiver` + `roles/pubsub.subscriber`.
- `luz_kubernetes_infra/terraform/devops/google-build-pipelines/main.tf`
  — `cloudbuild-bitbucket-sa`, `devops-cloudbuild-sa`.
- `luz_kubernetes_infra/terraform/devops/artifact-registry-container-images/main.tf`
  — `artifact-registry-reader` SA (has a downloaded key); writer access granted
  to `518364204428@cloudbuild.gserviceaccount.com` and
  `cloudbuild-bitbucket-sa@klara-infra.iam.gserviceaccount.com`.
- `luz_kubernetes/terraform-infra/tuwunel/serviceaccounts.tf` — `cloudbuild-github-tuwunel`
  (project `klara-infra`), `roles/compute.admin`, `roles/iam.serviceAccountUser`,
  `roles/storage.admin` (Terraform role) plus `roles/compute.instanceAdmin.v1`,
  `roles/storage.objectViewer` (Ansible role).
- `luz_kubernetes/terraform-infra/securemail-adm/sa.tf`,
  `luz_kubernetes/terraform-infra/luz-vault/sa.tf` — per-stack SAs.

## Common commands

```bash
# list SAs in a project
gcloud iam service-accounts list --project=klara-nonprod

# who has what role on a project
gcloud projects get-iam-policy klara-prod --flatten="bindings[].members" \
  --format="table(bindings.role,bindings.members)"

# check a GKE ServiceAccount's Workload Identity binding
kubectl get serviceaccount <name> -n <namespace> -o jsonpath='{.metadata.annotations}'

# grant WI binding (GSA <- KSA)
gcloud iam service-accounts add-iam-policy-binding \
  <gsa>@<project>.iam.gserviceaccount.com \
  --role roles/iam.workloadIdentityUser \
  --member "serviceAccount:<project>.svc.id.goog[<namespace>/<ksa>]"
```

## Safety notes

`klara-prod` is production. Never run `add-iam-policy-binding`,
`remove-iam-policy-binding`, `service-accounts delete`, or any `terraform apply`
touching IAM against `klara-prod` (or `klara-infra`, which controls CI/CD for
everything) without explicit user confirmation of the exact change first —
IAM mistakes lock people out or over-grant access. Read-only `get-iam-policy`/
`list` calls are always fine.

## Reference Directory

- `luz_kubernetes/configuration/env.sh` — SA naming convention source of truth.
- `luz_kubernetes/terraform/common-cloudrun-resources/base-resources/service-account/main.tf`
- `luz_kubernetes/terraform/common-cloudrun-resources/eventarc-pubsub-gke/main.tf`
- `luz_kubernetes_infra/terraform/devops/google-build-pipelines/main.tf`
- `luz_kubernetes_infra/terraform/devops/artifact-registry-container-images/main.tf`
- `luz_kubernetes/terraform-infra/tuwunel/serviceaccounts.tf`
