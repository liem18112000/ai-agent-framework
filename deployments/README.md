# deployments — Terraform for the Testing-Agent stack

Provisions everything the two agents run on: **Cloud Run** (two services — one per agent),
a shared **GCS** memory-bank bucket, **Vertex AI** access (Claude on Vertex, for the Distill /
LLM steps), a shared **Cloud SQL** Postgres task store, a single least-privilege **runtime
service account**, **Secret Manager** containers, and an **Artifact Registry** repo. Everything
runs the **same image** — only the container command differs.

## Topology — sidecar (agent + bridge in one service)

Each agent and its A2A→MCP bridge are **two containers in one Cloud Run service**:

```
Claude ──MCP/HTTPS──▶ knowledge-gathering-agent  [ bridge (ingress :8080, /mcp) ──localhost:8081──▶ agent (sidecar, private) ]
Claude ──MCP/HTTPS──▶ test-plan-definition-agent  [ bridge (ingress :8080, /mcp) ──localhost:8081──▶ agent (sidecar, private) ]
```

- The **bridge** is the ingress container (serves MCP `/mcp` on `$PORT`=8080); Claude connects here.
- The **agent** is a sidecar bound to `localhost:8081` — **never internet-exposed**. The bridge
  reaches it over localhost (no public agent URL, no cross-service hop).
- All containers in a service share **one** runtime SA (`kga-runtime`), which therefore holds the
  union of perms: Vertex + bucket + Cloud SQL + Atlassian + the bearer secrets.
- Session state lives in the bridge's memory, so each service pins to one warm instance
  (`session_affinity=true`, `min=max=1`). That single-instance pin drags the co-located agent too —
  fine for the low-concurrency (one-pipeline-at-a-time) usage. To scale the agent independently,
  externalize the bridge's session map first and split them back into separate services.

## File layout

| File | Contains |
|------|----------|
| `main.tf` | Shared infra: APIs, Artifact Registry, memory bucket, the `kga-runtime` SA + its IAM, the atlassian/a2a secrets. |
| `services.tf` | The two services — `module.kga` and `module.tpd`, each a bridge + agent container — plus the two bridge inbound-bearer secrets and the SA→secret IAM. |
| `modules/cloud_run_service/` | **One reusable Cloud Run v2 service** taking a `containers` list (one container sets `ingress_port`, the rest are sidecars) + `service_account_email`, `session_affinity`, `cloudsql_instance`, and an optional public invoker. |
| `cloudsql.tf` | Cloud SQL Postgres instance + DB + user + password secret + client IAM (the shared A2A task store). Toggle with `deploy_cloudsql`. |
| `variables.tf` / `outputs.tf` | All inputs / outputs. |
| `versions.tf` | Terraform + provider constraints (+ the optional remote-state backend). |

## What gets created

| Resource | Purpose |
|----------|---------|
| `google_project_service` ×7 | run, aiplatform, storage, secretmanager, artifactregistry, cloudbuild, sqladmin |
| `google_artifact_registry_repository` | Docker repo for the shared container image |
| `google_storage_bucket` | Memory bank (`notes/ index/ runs/`), UBLA + versioning + lifecycle |
| `module.kga` / `module.tpd` | The two services, each = bridge (ingress) + agent (sidecar) on the same image |
| `google_service_account` ×1 | `kga-runtime` — shared by every container of both services |
| `google_sql_database_instance` + database + user | Shared Postgres A2A task store (see `cloudsql.tf`) |
| IAM | `aiplatform.user` · `storage.objectAdmin` (bucket) · `cloudsql.client` · `secretmanager.secretAccessor` (per secret) — least privilege, all on `kga-runtime` |
| `google_secret_manager_secret` ×5 | `kga-atlassian-api-token`, `kga-a2a-bearer-token`, `kga-bridge-bearer-token`, `kga-tpd-bridge-bearer-token`, `kga-db-password` (values added out-of-band) |

## Apply

**One command:** `./deploy.sh` — provisions infra → adds secret versions (from `../test-agent/.env`) → builds+pushes the image → points both services at it. (`SKIP_BUILD=1` for infra only; `PLAN=1` to preview.)

> **Gotcha 1 — the build step "fails" but the build succeeds.** On accounts without Viewer/Owner
> on the Cloud Build log bucket, `gcloud builds submit` exits non-zero on a log-streaming error
> *even with `--suppress-logs`*, so `deploy.sh` (`set -e`) stops **after** the image is built but
> **before** its final `terraform apply -var=image=`. Recover by finishing that step, or submit
> the build with `--async` up front to avoid the streaming wait entirely:
> ```bash
> gcloud builds submit ../test-agent --tag "<image>" --async --project <project>
> gcloud builds describe <BUILD_ID> --project <project> --format='value(status)'   # expect SUCCESS
> terraform apply -var="image=<image>"
> ```

> **Gotcha 2 — migrating a single-container service to multi-container fails in-place.** Adding the
> agent sidecar to an existing single-container bridge errors with *"Revision template should contain
> exactly one container with an exposed port"* (terraform mis-assigns the port during the positional
> container diff), and the partial apply may destroy sibling resources first. Force a fresh create:
> ```bash
> terraform apply -replace='module.kga.google_cloud_run_v2_service.this[0]' \
>                 -replace='module.tpd.google_cloud_run_v2_service.this[0]' -var="image=<image>"
> ```
> The Cloud Run URL is stable across `-replace`, so Claude's registration is unaffected. Fresh
> (empty-state) applies create the two-container services correctly with no `-replace` needed; and
> ordinary image bumps are in-place (no container-count change), so they're unaffected too.

Manual steps (what the script does):

```bash
cd deployments
cp terraform.tfvars.example terraform.tfvars   # fill in project_id, atlassian_*, image, etc.

terraform init
terraform apply       # first apply uses a placeholder image so the services can be created

# add the secret VALUES (never in tfvars):
printf '%s' "$ATLASSIAN_API_TOKEN"     | gcloud secrets versions add kga-atlassian-api-token     --data-file=-
printf '%s' "$A2A_BEARER_TOKEN"        | gcloud secrets versions add kga-a2a-bearer-token        --data-file=-
printf '%s' "$KGA_BRIDGE_BEARER_TOKEN" | gcloud secrets versions add kga-bridge-bearer-token     --data-file=-
printf '%s' "$TPD_BRIDGE_BEARER_TOKEN" | gcloud secrets versions add kga-tpd-bridge-bearer-token --data-file=-

# build + push the real image, then point BOTH services at it (one image, one var):
gcloud builds submit ../test-agent --tag "<image>"
terraform apply -var="image=<image>"
```

Outputs: `bridge_url` / `tpd_bridge_url` — the MCP endpoints (`<service_url>/mcp`). There are no
agent URLs: the agents are private sidecars.

## The two containers per service (`services.tf` + `modules/cloud_run_service`)

Same **image**, two commands:

- **bridge** (ingress): `python -m <pkg>.bridge` → serves MCP over Streamable HTTP at `/mcp` on
  `$PORT`. Its `<PKG>_A2A_URL` points at `http://localhost:8081/` — the agent sidecar. `cpu_idle=false`
  + `startup_cpu_boost` keep the refine/define session warm.
- **agent** (sidecar): `uvicorn <pkg>.server:app --port 8081` → the A2A server, reachable only on
  localhost. It mounts the Cloud SQL socket and carries the Vertex / bucket / (Atlassian, kga only)
  env. Probed on `/livez` at port 8081.

**Auth topology.** Only the bridge is exposed. It is gated by its **own** inbound bearer secret
(`<PKG>_BRIDGE_BEARER_TOKEN`), distinct from the A2A bearer it forwards to the agent over localhost.
`bridge_allow_unauthenticated=true` makes the bridge publicly reachable (the inbound bearer is the
gate); set it `false` to keep the bridge private and reach it through a local authenticated proxy
(`./proxy.sh` → `gcloud run services proxy`), which owns the Google identity token. The agent is
never exposed either way, so the old "agent public + header collision" problem is gone.

Register with Claude (public-bridge form — restart Claude Code to load it):

```bash
claude mcp add --transport http knowledge-gathering  "$(terraform output -raw bridge_url)"
claude mcp add --transport http test-plan-definition "$(terraform output -raw tpd_bridge_url)"
```

## Cloud SQL task store (`cloudsql.tf`)

Both agent sidecars share a Postgres instance (`kga-taskstore`) as their **A2A task store** (durable
across Cloud Run revisions). It's mounted read/write via the Cloud SQL Auth proxy socket at
`/cloudsql`; the `DB_*` env + the `kga-db-password` secret feed `common.build_task_store()`, which
assembles the asyncpg URL. Toggle with `deploy_cloudsql` (off → in-memory task store). The bridge
containers don't mount it.

## Notes

- **One image, two services, four containers.** The Dockerfile installs the `.[bridge]` extra; each
  container just overrides the command (bridge → `python -m <pkg>.bridge`; agent → uvicorn). Bump the
  `image` tag once and a single `terraform apply -var=image=` rolls both services (in-place).
- **Vertex AI is not "provisioned"** beyond enabling the API + `roles/aiplatform.user`; the app calls
  **Claude on Vertex** (`anthropic[vertex]`) in `VERTEX_LOCATION` using `VERTEX_MODEL` (default
  `claude-sonnet-5`, which requires `vertex_region = global`).
- **Secrets are containers only.** `apply` succeeds, but a revision stays unhealthy until a version
  exists for each secret it mounts — add them as shown above.
- **State:** configure the `backend "gcs"` block in `versions.tf` for shared/remote state.
