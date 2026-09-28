# deployments/test-agent-v2 — Terraform for the ADK (v2) Testing-Agent stack

> **The ADK (v2) Testing-Agent stack** — distinct `…-v2` Cloud Run service names, its own secrets/SA
> (`name_prefix = "kga-v2"`), its own memory bucket (`<project>-kga-v2-memory`), and its own
> terraform state.
> **Single-gateway topology (G2):** one `mcp-gateway-v2` service is the only MCP endpoint Claude
> connects to; the three agents are **A2A-only** and reached by the gateway over A2A.
> `deploy_cloudsql` defaults **on**: v2 stands up its **own** Cloud SQL Postgres instance (durable
> `DatabaseSessionService`), isolated per stack (extra cost) — set `false` for in-memory sessions (the
> GCS bank stays durable regardless). Build context: `../../test-agent-v2`.

Provisions: **Cloud Run** (four services — the gateway + three A2A agents), a shared **GCS**
memory-bank bucket, **Vertex AI** access (Claude on Vertex), a **Cloud SQL** Postgres session/task
store, one least-privilege **runtime SA**, **Secret Manager** containers, and an **Artifact
Registry** repo. Everything runs the **same image** — only the container command differs.

## Topology — one gateway, three A2A-only agents

```
                         ┌───────────────────────────── A2A + A2A_BEARER ──────────────┐
Claude ──MCP/HTTPS──▶ mcp-gateway-v2 (ingress :8080, /mcp) ──┬──▶ knowledge-gathering-agent-v2 (A2A :8080)
   (GATEWAY_BEARER)                                          ├──▶ test-plan-definition-agent-v2 (A2A :8080)
                                                             └──▶ test-evaluation-agent-v2      (A2A :8080)
```

- The **gateway** is the single ingress Claude connects to (`python -m gateway`, MCP `/mcp` on
  `$PORT`=8080). It exposes every tool and routes each call to the right agent over A2A. Gated by
  `GATEWAY_BEARER_TOKEN`; holds the per-agent multi-turn task maps in memory → `session_affinity`,
  `min=max=1`.
- Each **agent** is a single-container A2A service (`uvicorn main:app` on :8080, agent chosen by the
  `AGENT` env), public but gated by the shared `A2A_BEARER_TOKEN`; the gateway calls it with that
  bearer. (Was a 2-container agent+bridge sidecar before G2; the per-agent bridges were removed.)
- All containers share **one** runtime SA (`kga-v2-runtime`): Vertex + bucket + Cloud SQL + Atlassian
  + the bearer secrets.

## File layout

| File | Contains |
|------|----------|
| `main.tf` | Shared infra: APIs, Artifact Registry, memory bucket, the `kga-v2-runtime` SA + IAM, the atlassian/a2a secrets. |
| `services.tf` | `module.kga`/`module.tpd`/`module.tev` (single agent container each) + `module.gateway` + the `kga-v2-gateway-bearer-token` secret + SA→secret IAM. |
| `modules/cloud_run_service/` | One reusable Cloud Run v2 service taking a `containers` list (one sets `ingress_port`) + `service_account_email`, `session_affinity`, `cloudsql_instance`, optional public invoker. |
| `cloudsql.tf` | Cloud SQL Postgres instance + DB + user + password secret + client IAM. Toggle with `deploy_cloudsql`. |
| `variables.tf` / `outputs.tf` | All inputs / outputs. |
| `versions.tf` | Terraform + provider constraints (+ optional remote-state backend). |

## What gets created

| Resource | Purpose |
|----------|---------|
| `google_project_service` ×7 | run, aiplatform, storage, secretmanager, artifactregistry, cloudbuild, sqladmin |
| `google_artifact_registry_repository` | Docker repo for the shared image (`kga-v2`) |
| `google_storage_bucket` | Memory bank (`notes/ index/ runs/`), UBLA + versioning + lifecycle |
| `module.gateway` | The single MCP gateway service (`mcp-gateway-v2`) |
| `module.kga`/`module.tpd`/`module.tev` | The three A2A-only agent services, same image |
| `google_service_account` ×1 | `kga-v2-runtime` — shared by every container |
| `google_sql_database_instance` + database + user | Cloud SQL Postgres session/task store (see `cloudsql.tf`) |
| IAM | `aiplatform.user` · `storage.objectAdmin` · `cloudsql.client` · `secretmanager.secretAccessor` (per secret), all on `kga-v2-runtime` |
| `google_secret_manager_secret` ×5 | `kga-v2-atlassian-api-token`, `kga-v2-bitbucket-app-password`, `kga-v2-a2a-bearer-token`, `kga-v2-gateway-bearer-token`, `kga-v2-db-password` |

## Apply

**One command:** `./deploy.sh` — first-deploy-safe order: secret containers + versions (from
`../../test-agent-v2/.env`) → artifact repo → **build image** → full `terraform apply`. The image is
built **before** the services because each container overrides the entrypoint to run uvicorn/the
gateway, so the `hello` placeholder can't boot. (`SKIP_BUILD=1` for apply-only; `PLAN=1` to preview.)

> **Cloud Build "fails" but the build succeeds.** On accounts without Viewer/Owner on the Cloud
> Build log bucket, a synchronous `gcloud builds submit` exits non-zero on a log-streaming error even
> with `--suppress-logs`. `deploy.sh` avoids this by submitting with `--async` and polling
> `gcloud builds describe <id> --region=global` for the real `SUCCESS`/`FAILURE` — never trusting the
> submit exit code.

> **First apply + Cloud SQL db-password.** The terraform-generated `kga-v2-db-password` secret
> *version* can race the service that mounts it on a first apply; `deploy.sh` retries the final apply
> once, which clears it.

Outputs: `gateway_url` — the one MCP endpoint (`<gateway_service_url>/mcp`); `kga_a2a_url` /
`tpd_a2a_url` / `tev_a2a_url` — the agents' A2A base URLs (informational; the gateway's `*_A2A_URL`).

## Register with Claude Code

Deploy first, then register the **single** gateway (idempotent; resolves `gateway_url` from
`terraform output`, reads `GATEWAY_BEARER_TOKEN` from `../../test-agent-v2/.env`; restart Claude Code
after):

```bash
./install-mcp.sh                # or: install-mcp.cmd on Windows
./install-mcp.sh --scope user   # register in every project
```

ADK has no native MCP-server (its `McpToolset` only *consumes* MCP tools), so this A2A→MCP gateway is
Claude Code's native channel to the agents. Under the hood:

```bash
claude mcp add --transport http testing-agent "$(terraform output -raw gateway_url)" \
  --header "Authorization: Bearer $GATEWAY_BEARER_TOKEN"
```

`bridge_allow_unauthenticated=true` (default) makes the gateway + agents publicly reachable, gated by
their bearers. Set it `false` to keep them private and reach the gateway through a local authenticated
proxy (`./proxy.sh` → `gcloud run services proxy`).

## Cloud SQL session/task store (`cloudsql.tf`)

The agents share a Postgres instance (`kga-v2-taskstore`) as ADK's durable `DatabaseSessionService` /
A2A task store (survives Cloud Run revisions), mounted via the Cloud SQL Auth proxy socket at
`/cloudsql`; the `DB_*` env + the `kga-v2-db-password` secret feed it. The gateway does **not** mount
Cloud SQL — it talks only A2A. Toggle with `deploy_cloudsql` (off → in-memory).

## Notes

- **One image, four services.** The Dockerfile installs `.[bridge]`; each container overrides the
  command (gateway → `python -m gateway`; agents → `uvicorn main:app` with a per-service `AGENT` env).
  Bump `image` once and one `terraform apply -var=image=` rolls all four (in-place).
- **Vertex AI** isn't "provisioned" beyond enabling the API + `roles/aiplatform.user`; the app calls
  **Claude on Vertex** in `VERTEX_LOCATION` using `VERTEX_MODEL` (default `claude-sonnet-5`, which
  requires `vertex_region = global`).
- **Secrets are containers only.** `apply` succeeds, but a revision stays unhealthy until a version
  exists for each secret it mounts — `deploy.sh` adds them (the DB password is terraform-generated).
- **State:** configure the `backend "gcs"` block in `versions.tf` for shared/remote state.
