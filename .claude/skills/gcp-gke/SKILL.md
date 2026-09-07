---
name: gcp-gke
description: >-
  GKE expert for the LUZ ops repo — cluster inventory, node pools, Workload
  Identity, namespaces, and kustomize overlays across klara-nonprod/prod/
  performance/infra. Use when inspecting, scaling, upgrading, or debugging a
  GKE cluster or workload, or applying kustomize overlays under
  kubernetes-overlays/. Don't use for IAM/service-account grants alone (see
  gcp-iam), VPC/firewall design (see gcp-network), or Cloud Run (see
  gcp-cloudrun).
metadata:
  category: Containers
---

# GKE — LUZ Ops

Cluster inventory and conventions across `luz_kubernetes` and
`luz_kubernetes_infra`.

## Environments

Region **europe-west6** (zone `-a`) everywhere except `klara-dev-vn`
(**asia-southeast1-a**). All clusters: VPC-native, private nodes
(`master_ipv4_cidr_block = 172.16.0.0/28`), Workload Identity
(`<project>.svc.id.goog`), Gateway API `CHANNEL_STANDARD`,
`remove_default_node_pool = true`, `deletion_protection = false`.

## Known clusters

| Cluster | Project | Zone/Region | Node pool shapes |
|---|---|---|---|
| `klara-infra` | klara-infra | europe-west6-a | n1-highmem-8 default; IVY n1-highmem-8; antivirus n1-highcpu-16; docs/mongodb n1-standard-8 |
| `klara-nonprod` | klara-nonprod | europe-west6-a | e2-highmem-8 (large e2-highmem-16); IVY e2-standard-16; antivirus e2-highcpu-8 |
| `klara-prod` | klara-prod | europe-west6-a | e2-highmem-16 (large e2-standard-32); IVY e2-standard-16; antivirus e2-highcpu-16 |
| `klara-performance` | klara-performance | europe-west6-a | n1-highmem-8; IVY n1-standard-16; mongodb n1-standard-8 |
| `klara-dev-vn` | klara-nonprod | asia-southeast1-a | n1-highmem-8 / IVY n1-highmem-8 / antivirus n1-highcpu-16 |
| `klara-prod-secmail` / `klara-nonprod-secmail` | klara-prod / klara-nonprod | europe-west6-a | secmail-only shapes |
| `klara-nonprod-communities` / `klara-prod-communities` (Tuwunel/Matrix) | klara-nonprod / klara-prod | europe-west6-a | n2-standard-32, max 6 nodes; prod uses pd-extreme disks |
| `klara-nonprod-securemail-milter` / `klara-prod-securemail-milter` | klara-nonprod / klara-prod | europe-west6-a | e2-standard-4 (+ `wi-pool` e2-standard-2 for Workload Identity) |
| `klara-nonprod-secmail` (cluster module) | klara-nonprod | europe-west6-a | n2-standard-8, max 2 nodes, pd-standard |
| `klara-prod-secmail` (cluster module) | klara-prod | europe-west6-a | c2-standard-16, max 6 nodes, pd-ssd |

Config source: `luz_kubernetes/configuration/cluster-gcp-{nonprod,prod,performance,dev-vn,prod-secmail,nonprod-secmail}/env.sh`,
`luz_kubernetes_infra/configuration/cluster-gcp-infra/env.sh`, and `gke.tf`
under `luz_kubernetes/terraform-infra/{tuwunel,securemail-milter,securemail}/`
and `_modules/simple-vpc-cluster/modules/cluster/gke.tf`.

## Namespaces (kustomize)

From `luz_kubernetes/kubernetes-overlays/*/kustomization.yaml`: `dev`,
`dev-vn`, `dev-staging`, `devgcp`, `test`, `performance`, `prod`, `swissdec`,
plus secmail variants (`dev-secmail`, `dev-secmail-adm`, `dev-secmail-milter`,
`performance-secmail`, `prod-secmail`, `prod-secmail-milter`, `test-secmail`)
and per-env MongoDB-cluster namespaces. `luz_kubernetes_infra` overlays use
`infra`, `cloudbuild`.

## Common commands

```bash
# get credentials for a cluster
gcloud container clusters get-credentials klara-nonprod --zone europe-west6-a --project klara-nonprod

# list node pools
gcloud container node-pools list --cluster klara-prod --zone europe-west6-a --project klara-prod

# apply an overlay (dry-run first)
kubectl kustomize luz_kubernetes/kubernetes-overlays/env-dev | kubectl diff -f -
kubectl apply -k luz_kubernetes/kubernetes-overlays/env-dev

# check workload identity annotation on a namespace's SAs
kubectl get sa -n dev -o custom-columns=NAME:.metadata.name,GSA:.metadata.annotations.iam\.gke\.io/gcp-service-account
```

## Safety notes

`klara-prod`, `klara-prod-secmail`, `klara-prod-communities`, and
`klara-prod-securemail-milter` are production clusters. Always run
`kubectl diff` / `kubectl apply -k ... --dry-run=server` and show the user the
diff before `kubectl apply` or `terraform apply` against any prod cluster.
Never delete a node pool or run `terraform destroy` without explicit
confirmation naming the exact cluster.

## Reference Directory

- `luz_kubernetes/configuration/cluster-gcp-*/env.sh` — per-cluster shapes.
- `luz_kubernetes/terraform-infra/tuwunel/gke.tf`, `securemail-milter/gke.tf`,
  `securemail/modules/cluster/gke.tf`, `_modules/simple-vpc-cluster/modules/cluster/gke.tf`
- `luz_kubernetes/kubernetes-overlays/` — all kustomize overlays.
- `luz_kubernetes_infra/kubernetes-overlays/` — infra/cloudbuild namespace overlays.
