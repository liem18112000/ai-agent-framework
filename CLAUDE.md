# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

`ops` is the superproject for the KLARA/LUZ platform's deployment estate. It is not an application
codebase — there is no single build/lint/test command because the repo's job is to hold
Kubernetes manifests, Terraform, encrypted secrets, and Dockerfile sources for ~150+ services, plus
a couple of Python-based ops agents. Nearly all real work happens in three git submodules (siblings
on Bitbucket, not vendored copies):

| Path | Purpose |
|---|---|
| `luz_kubernetes/` | Main deploy repo — Kubernetes manifests (`kubernetes/`), per-environment kustomize overlays (`kubernetes-overlays/`), Terraform for Cloud Run + supporting infra (`terraform/`, `terraform-infra/`), env configs (`configuration/`), SOPS-encrypted secrets (`sops/`), deploy tooling (`utilities/`, `deploy_to_stdout.sh`, `deploy_terraform.sh`) |
| `luz_kubernetes_infra/` | Same pattern as above, but for the shared `klara-infra` cluster (devportal, cloud-builders, cloud-functions) |
| `luz_dockerfiles/` | Dockerfile sources for base/sidecar images (wildfly variants, quarkus, vault, clamav, mjml, etc.), each self-contained with its own `build.sh` |

Plus, in the superproject itself:

- `agent/devops/` — `devops-3f9a`, a Vertex AI Agent Engine GKE ops agent (see below).
- `.claude/skills/gcp-*/` — one reference skill per GCP domain (IAM, GKE, Cloud Run, Pub/Sub, Secret
  Manager, GCS, network, observability). **Load the matching skill before doing anything
  domain-specific** — they hold the actual inventories (clusters, services, projects, naming
  conventions) and are kept current; don't re-derive or duplicate that here.

## Critical: submodules are sibling repos, not nested ones

`.gitmodules` must use `../<name>` URLs with an explicit `branch = master` for each submodule. This
already broke once: an earlier `./name` (single dot) form resolved, via Bitbucket's smart-HTTP
handling of relative submodule URLs, to a *nested* path inside this superproject's own repo instead
of the sibling repo — and silently served the superproject's own near-empty history. Running a naive
fetch+checkout against that then overwrote all three submodules' working trees with the wrong
content. Never revert `.gitmodules` back to `./name` style URLs, and if a 4th submodule is ever
added, use `../<name>` with `branch =` set explicitly.

Separately, plain `git submodule update --init --recursive` leaves each submodule in detached HEAD
at whatever SHA the superproject's commit recorded — not "latest". Use the `git-submodule-sync`
skill (`bash .claude/skills/git-submodule-sync/scripts/sync-submodules.sh`) to fast-forward all three
to the tip of `master` before starting work in them, and always review `git diff --submodule` before
committing the resulting pointer bump.

## Environments and projects

- GCP projects: `klara-nonprod`, `klara-prod`, `klara-performance`, `klara-infra` (+ `klara-repo` for
  the artifact registry).
- Region `europe-west6` (zone `-a`) everywhere except `klara-dev-vn` (`asia-southeast1-a`).
- Kubernetes namespaces / kustomize overlays: `dev`, `dev-vn`, `dev-staging`, `devgcp`, `test`,
  `performance`, `prod`, `swissdec`, plus several `*-secmail*` variants and per-env MongoDB namespaces.
- Terraform (Cloud Run, `luz_kubernetes/terraform/`): one workspace per environment (`dev`, `dev-vn`,
  `dev-staging`, `test`, `performance`, `prod`), state in GCS bucket `luz-terraform`.

Full cluster/service inventories live in the `gcp-gke` and `gcp-cloudrun` skills — read those instead
of grepping the configuration trees from scratch.

## Secrets — two distinct patterns

1. **SOPS-encrypted Kubernetes Secret YAML** — `sops/.sops.yaml` maps environment path patterns to a
   PGP key (prod additionally wraps with `gcp_kms`); `sops/scripts/` has one `*-create-*-secret.sh`
   script per application secret (~250 scripts). CI imports the GPG keys before decrypting.
2. **Native GCP Secret Manager**, used for Cloud Run services.

See the `gcp-secretmanager` skill for which pattern applies where.

## CI/CD (Cloud Build)

Two pipelines share the same underlying script (`utilities/deploy_and_validate.sh <env> [options]`,
run inside the shared `luz-deploy` image) and both gate first on
`utilities/detect_invalid_deployment_or_secret.sh`, Slack-notifying per environment on failure via
`utilities/notify_deployment_status.sh` / `utilities/slack_author_map.sh`:

- `cloudbuild-validate.yaml` — hardcodes `--dry-run`: generates manifests and validates references,
  never applies.
- `cloudbuild-deploy-and-validate.yaml` — the same pipeline without `--dry-run`: actually applies.

Both are driven by Cloud Build substitutions: `_ENVIRONMENT` (single or comma-separated env list),
`_ROLLOUT_TIMEOUT`, `_SKIP_PRE_CHECK` / `_SKIP_POST_CHECK` / `_SKIP_CRONJOB_CHECK`, and
`_EXCLUDE_MODULES` / `_ONLY_MODULES` (mutually exclusive). Cloud Build only substitutes the literal
`${_VAR}` pattern — it does not support bash-style `${_VAR:-default}` — so defaults live in the
`substitutions:` block instead.

## Common commands

```bash
# sync submodules to latest master before working in them
bash .claude/skills/git-submodule-sync/scripts/sync-submodules.sh

# GKE — get cluster creds, then use kubectl as normal
gcloud container clusters get-credentials <cluster> --zone europe-west6-a --project <project>

# apply a kustomize overlay — always diff first
kubectl kustomize luz_kubernetes/kubernetes-overlays/env-<env> | kubectl diff -f -
kubectl apply -k luz_kubernetes/kubernetes-overlays/env-<env>

# generate + validate + (optionally) apply manifests for one environment
cd luz_kubernetes
./utilities/deploy_and_validate.sh <env> --dry-run
./utilities/deploy_and_validate.sh <env> --skip-cronjob-check --timeout 300

# Terraform (Cloud Run), from luz_kubernetes/terraform
terraform workspace select <env>
terraform plan

# validate a single overlay/config pair against configuration/env.sh
cd luz_kubernetes/kubernetes && ./validate.sh <gcp-project> <environment>
```

There is no unit test suite for the Terraform/Kubernetes/Dockerfile content — validation is the
Cloud Build dry-run pipeline and the `validate.sh` / `deploy_and_validate.sh` scripts above. The
`devops-3f9a` agent (`agent/devops/`) has no pytest suite either; it's exercised with standalone
scripts run directly: `python mcp_bridge/test_bridge_logic.py` (calls `server.py` logic in-process)
and `python smoke_test.py` (hits the deployed Agent Engine).

## devops-3f9a (agent/devops/)

A GKE ops agent built on Google's ADK, deployed to Vertex AI Agent Engine, wired into this session as
the `devops-3f9a` MCP server (`.mcp.json`) via a local stdio bridge (`mcp_bridge/server.py`) exposing
`ask_devops_agent(message, session_id)` and `confirm_devops_agent_action(session_id, approve)`.

- Project scope is enforced in code, not just the prompt: every tool calls
  `devops_3f9a/config.py:assert_project_allowed`, which rejects `klara-prod` regardless of what's
  asked. Allowed projects: `klara-nonprod`, `klara-performance`, `klara-infra`, `klara-repo`.
- Mutating tools (`resize_node_pool`, `restart_deployment`, `scale_deployment`) require an explicit
  confirmation round-trip (ADK `require_confirmation=True`); read tools (`list_clusters`,
  `get_cluster`, `list_node_pools`, `list_pods`, `get_pod_logs`) don't.
- Install: `uv venv --python 3.12` then `uv pip install` the exact pinned versions in
  `pyproject.toml` (versions are pinned deliberately — `google-adk` broke tool APIs between minor
  versions). Deploy: `python deployment/deploy.py`. Full steps, including required one-time IAM
  grants, are in `agent/devops/DEPLOY.md`.

## Safety notes

- `klara-prod` and its associated clusters/workspaces are live production. Always show a
  `terraform plan` / `kubectl diff` / `kubectl apply -k ... --dry-run=server` before applying
  against prod, and confirm the exact resource(s) affected before any `terraform apply`,
  `terraform destroy`, or `kubectl delete`.
- Internal-only Cloud Run services (`INGRESS_TRAFFIC_INTERNAL_ONLY`, e.g. `luz-message-broker`)
  should never be flipped to public ingress without explicit confirmation.
- A submodule sync pulls in unreviewed upstream changes into the working tree; review
  `git diff --submodule` before committing the pointer bump, especially on `feature/ops` or
  `master` — that bump changes what Cloud Build actually deploys.
