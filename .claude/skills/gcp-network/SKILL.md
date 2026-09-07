---
name: gcp-network
description: >-
  VPC/networking expert for the LUZ ops repo — VPC/subnet naming, CIDR
  allocations, Cloud NAT, dedicated VPCs per stack, firewall rules, and
  Private Service Connect endpoints. Use when inspecting or changing a VPC,
  subnet, firewall rule, Cloud NAT, or PSC endpoint. Don't use for GKE
  cluster/node-pool config alone (see gcp-gke) or Cloud Run ingress alone (see
  gcp-cloudrun).
metadata:
  category: Networking
---

# VPC / Networking — LUZ Ops

## Core network naming (per env, from `env.sh`)

- `LUZ_GCP_CUSTOM_NETWORK=luz-custom-network-cloud-nat` (dev-vn:
  `luz-custom-network-cloud-nat-vn`)
- `LUZ_GCP_DEFAULT_NAT_ROUTER=luz-default-nat-router`,
  `LUZ_GCP_DEFAULT_NAT_GATEWAY=luz-default-nat-gateway`
- `LUZ_GCP_SUBNET_NAME=subnet-europe-west6`

| Env | Subnet CIDR |
|---|---|
| nonprod | 192.168.1.0/24 |
| prod | 192.168.99.0/24 |
| infra | 10.128.0.0/24 |
| dev-vn | 192.168.1.0/24 |

Cloud Run dedicated subnets (`luz_kubernetes/terraform/common-cloudrun-resources/base-resources/network/main.tf`,
pattern `<workspace>-<location>-cloudrun-subnet`): prod `172.18.0.0/16`, dev
`192.168.10.0/23`, test `192.168.40.0/23`, dev-vn `192.168.10.0/23`,
performance `192.167.0.0/20`, dev-staging `192.168.30.0/24`.

## Dedicated per-stack VPCs

- **Tuwunel (Matrix/communities)**: `luz-custom-network-cloud-nat-communities`,
  subnet `subnet-europe-west6-communities` (192.168.0.0/20), pods
  10.0.0.0/14, services 10.4.0.0/20, proxy-only subnet 192.168.16.0/23
  (`terraform-infra/tuwunel/{nonprod,prod}.tfvars`).
- **Secure-mail milter**: VPC `luz-secure-mail-milter`, subnet
  `luz-secure-mail-milter-subnet`, router `luz-secure-mail-milter-router`, NAT
  `luz-secure-mail-milter-cloudnat`
  (`terraform-infra/securemail-milter/{nonprod,prod}.tfvars`).
- **Secure-mail (legacy)**: firewall rules in
  `terraform-infra/securemail/network.firewall.tf` —
  `cluster-subnet-allow-smtp`, `cluster-subnet-allow-https-selected`,
  `allow_pod_ips`, `allow_https_main`, `allow_https`, `allow_ssh_gcloud`.

No `google_compute_firewall` Terraform resources exist for the main
`klara-nonprod`/`klara-prod`/`klara-infra` GKE clusters themselves — only for
the secure-mail cluster module.

## Private Service Connect

`luz_kubernetes_infra/configuration/env-infra/env.sh`:
`dev-api-forwarder-psc-endpoint` / `dev-api-forwarder-psc-attachment` (→
klara-nonprod); `infra-proxy-forwarder-psc-endpoint` /
`infra-proxy-forwarder-psc-att` (→ klara-prod).

## Common commands

```bash
# list VPCs / subnets
gcloud compute networks list --project klara-nonprod
gcloud compute networks subnets list --project klara-nonprod --filter="region:europe-west6"

# list firewall rules
gcloud compute firewall-rules list --project klara-prod

# check Cloud NAT / router status
gcloud compute routers nats describe luz-default-nat-gateway \
  --router=luz-default-nat-router --region=europe-west6 --project=klara-nonprod
```

## Safety notes

Firewall and NAT changes on `klara-prod` or the secure-mail VPCs can cut
production traffic instantly. Always `terraform plan` / dry-run and confirm
the exact rule/CIDR with the user before applying. Never widen a firewall
rule's source ranges to `0.0.0.0/0` without explicit confirmation.

## Reference Directory

- `luz_kubernetes/configuration/*/env.sh` — network naming per cluster env.
- `luz_kubernetes/terraform/common-cloudrun-resources/base-resources/network/main.tf`
- `luz_kubernetes/terraform-infra/tuwunel/{network.tf,cloudnat.tf}`
- `luz_kubernetes/terraform-infra/securemail-milter/{network.tf,cloud-nat.tf}`
- `luz_kubernetes/terraform-infra/securemail/network.firewall.tf`
