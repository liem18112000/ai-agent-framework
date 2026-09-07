---
name: gcp-secretmanager
description: >-
  Secret Manager expert for the LUZ ops repo — the two secret-delivery
  patterns in use (native GCP Secret Manager for Cloud Run, SOPS-encrypted
  Kubernetes Secrets for GKE) and how they differ. Use when adding, rotating,
  or inspecting a secret for a Cloud Run service or a GKE workload. Don't use
  for IAM role grants alone (see gcp-iam) or for general GCS bucket access
  (see gcp-gcs).
metadata:
  category: Security
---

# Secret Manager — LUZ Ops

Two distinct, non-interchangeable patterns are in use. **There is no Secrets
Store CSI Driver / `SecretProviderClass` anywhere in this repo** — GKE never
mounts native GCP Secret Manager secrets directly.

## Pattern 1 — Cloud Run: native GCP Secret Manager

- `luz_kubernetes/terraform/luz-storage-services/template/main.tf:36-44` —
  volume `gcs-credential` sourced from `var.gcs_secret_name`, mounted at
  `/credential`; IAM binding `roles/secretmanager.secretAccessor` granted to
  the Cloud Run service account (`google_secret_manager_secret_iam_member.secret_access`).
- `luz_kubernetes/terraform/luz-message-broker/main.tf:67-75,142-151` —
  `pubsub_adminsdk_secret` (env `secret_key_ref`) and `run_as_token_secret`
  (volume mount at `/secrets/run-as-token`), both `secretAccessor`.
- `luz_kubernetes_infra/terraform/devops/google-build-pipelines/main.tf:49-127`
  — Bitbucket connection secrets: `bitbucket-admin-access-token`,
  `bitbucket-read-access-token`, `bitbucket-webhook-token`,
  `bitbucket-read-write-access-token`.
- Cloud Build pipeline secret `slack-webhook-url`, referenced as
  `projects/518364204428/secrets/slack-webhook-url/versions/1` in
  `luz_kubernetes/cloudbuild-deploy-and-validate.yaml:127` and
  `cloudbuild-validate.yaml:154` (`availableSecrets.secretManager`).
- Manual upload: `luz_kubernetes/cluster/gcp/manual_script/upload-incamail-po-private-key-to-gcp-secret-manager.sh`
  (per-env partner JWT private key).

## Pattern 2 — GKE: SOPS-encrypted Kubernetes Secrets

Secrets for GKE workloads are plain Kubernetes `Secret` manifests encrypted
with SOPS, checked into `luz_kubernetes/kubernetes-overlays/env-*/...` (e.g.
`luz-vault-encryption-key-secret.sops.yaml`,
`luz-notification-center-firebase-secret.sops.yaml`,
`luz-audit-storage-key-env-secret.sops.yaml` — dozens of examples). Decrypted
at deploy time via `gpg --import /opt/keys/<env>/*` in
`cloudbuild-deploy-and-validate.yaml:31`, then applied by kustomize. These are
**not** GCP Secret Manager objects — never look for them in `gcloud secrets
list`.

## Common commands

```bash
# Cloud Run / native Secret Manager
gcloud secrets list --project klara-nonprod
gcloud secrets versions access latest --secret=<name> --project klara-prod   # read value — be careful
gcloud secrets get-iam-policy <name> --project klara-nonprod

# GKE / SOPS secrets — decrypt to inspect, never commit plaintext
sops -d luz_kubernetes/kubernetes-overlays/env-dev/<path>/luz-vault-encryption-key-secret.sops.yaml
```

## Safety notes

Never run `gcloud secrets versions access` against a `klara-prod` secret and
print/log the value unless the user explicitly asks to see that exact secret.
Never decrypt a `*.sops.yaml` and write the plaintext to a file that isn't
immediately discarded — SOPS files are checked into git precisely because
they're safe encrypted; a stray plaintext copy is not. Never `gcloud secrets
delete` or overwrite a version without explicit confirmation naming the exact
secret and environment.

## Reference Directory

- `luz_kubernetes/terraform/luz-storage-services/template/main.tf`
- `luz_kubernetes/terraform/luz-message-broker/main.tf`
- `luz_kubernetes_infra/terraform/devops/google-build-pipelines/main.tf`
- `luz_kubernetes/kubernetes-overlays/env-*/**/*.sops.yaml`
- `luz_kubernetes/cloudbuild-deploy-and-validate.yaml` (gpg import step)
