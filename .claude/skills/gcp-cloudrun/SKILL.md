---
name: gcp-cloudrun
description: >-
  Cloud Run expert for the LUZ ops repo — service inventory, the shared
  Terraform service-template module, and workspace-per-environment deploys
  under luz_kubernetes/terraform. Use when inspecting, deploying, or debugging
  a Cloud Run service, or adding a new service from the shared template.
  Don't use for GKE workloads (see gcp-gke), Pub/Sub topic/subscription design
  alone (see gcp-pubsub), or Secret Manager mounts alone (see
  gcp-secretmanager).
metadata:
  category: Serverless
---

# Cloud Run — LUZ Ops

All Cloud Run infra lives in `luz_kubernetes/terraform/`, region
**europe-west6**, images from
`europe-west6-docker.pkg.dev/klara-repo/artifact-registry-container-images/...`.
Terraform state: GCS bucket `luz-terraform`, prefix `state`, one **workspace
per environment**: `dev`, `dev-vn`, `dev-staging`, `test`, `performance`,
`prod` (`luz_kubernetes/terraform/main.tf`).

## Known services

| Service | Terraform path | Notes |
|---|---|---|
| `luz-message-broker` | `terraform/luz-message-broker/main.tf` | `google_cloud_run_v2_service`, `INGRESS_TRAFFIC_INTERNAL_ONLY` |
| `luz-storage-services` | `terraform/luz-storage-services/template/main.tf` | per-service template |
| `luz-antivirus` | `terraform/luz-antivirus/main.tf` | |
| `luz-thumbnail` | `terraform/luz-thumbnail/main.tf` | |
| `luz-epc-services` | `terraform/luz-epc-services/main.tf`, `services/main.tf` | Direct VPC egress |
| `luz-epc-websocket-service` | `terraform/luz-epc-websocket-service/main.tf` | |
| `luz-salary-run` | `terraform/cloudrun/luz-salary-run/main.tf` | enabled: performance, dev, dev-vn, dev-staging, test, prod |
| `serverless-workflow-runtime` | `terraform/cloudrun/serverless-workflow-runtime/main.tf` | enabled: dev, dev-vn, performance; optional Eventarc→GKE via `eventarc.tf` |
| `dummy-orchestrator` | `terraform/dummy-orchestrator/main.tf` | |
| `notify-software-release` | `luz_kubernetes_infra/cloud-functions/notify-software-release` | invoker binding in `google-pub-sub/main.tf` |
| `epost-workflow` | `terraform/epost-workflow/main.tf` | **defined but commented out / not deployed** (`terraform/main.tf:117-121`) |

Shared module: `luz_kubernetes/terraform/common-cloudrun-resources/service-template/`
— reusable Cloud Run + Pub/Sub template every new service should start from.
Also: `base-resources/network` (Cloud Run subnets), `base-resources/service-account`,
`base-resources/secret`, `base-resources/cloudrun-invoker-iam`.

## Common commands

```bash
# list Cloud Run services in a project
gcloud run services list --project klara-nonprod --region europe-west6

# describe a service
gcloud run services describe luz-message-broker --project klara-prod --region europe-west6

# terraform plan for one workspace (from luz_kubernetes/terraform)
terraform workspace select dev
terraform plan

# tail logs
gcloud run services logs read luz-antivirus --project klara-nonprod --region europe-west6 --limit 100
```

## Safety notes

The `prod` Terraform workspace deploys to `klara-prod`. Always `terraform plan`
and show the diff before `terraform apply -workspace prod`, and confirm the
exact resource(s) affected. `luz-message-broker` and other internal-only
services (`INGRESS_TRAFFIC_INTERNAL_ONLY`) should never be flipped to public
ingress without explicit confirmation.

## Reference Directory

- `luz_kubernetes/terraform/main.tf` — root module wiring all services per workspace.
- `luz_kubernetes/terraform/common-cloudrun-resources/service-template/` — the template to copy for a new service.
- `luz_kubernetes/terraform/common-cloudrun-resources/eventarc-pubsub-gke/` — Eventarc→GKE wiring pattern.
