# Deploying the v2 ADK agents — the real options

How ADK agents are *actually* deployed (confirmed against the installed `adk` CLI 2.8.0 and the
official docs at <https://adk.dev/deploy/>), and how each maps onto this repo. There are **four**
paths; pick by what the consumer needs.

Prereq for the ADK-native paths: each agent is a package under `src/` with `agent.py:root_agent` and
an `__init__.py` that imports it — which is exactly the E1 layout (`adk` discovers all four:
`knowledge_gathering`, `test_plan_definition`, `test_evaluation`, `testing_agent`).

---

## 1. `adk deploy cloud_run` — the canonical Cloud Run path (ADK-native)

ADK packages the agent, generates a container that runs its **own FastAPI API server**
(`get_fast_api_app`), and `gcloud run deploy`s it:

```bash
adk deploy cloud_run \
  --project=$GOOGLE_CLOUD_PROJECT --region=$GOOGLE_CLOUD_LOCATION \
  --service_name=testing-agent-v2 --with_ui \
  src/testing_agent            # or any agent package dir
```

Serves the **ADK REST/SSE API**: `POST /run`, `POST /run_sse`, `GET /list-apps`, and the session /
artifact endpoints (`/apps/{app}/users/{user}/sessions/…`); `--with_ui` adds the `adk web` dev UI
(dev only). Durable stores via `--session_service_uri` / `--artifact_service_uri` /
`--memory_service_uri`. This is **not** A2A and **not** the MCP bridge — clients call ADK's HTTP API.

## 2. Manual Cloud Run container — same server, your Dockerfile ([`../main.py`](../main.py))

Identical server, but you own the container (this repo ships it): `main.py` calls
`get_fast_api_app(agents_dir="src", a2a=True, …)` — serving the ADK REST API **and** A2A for all four
agents — and the `Dockerfile` runs `uvicorn main:app`. Deploy with:

```bash
gcloud run deploy testing-agent-v2 --source . --region $REGION --project $PROJECT \
  --set-env-vars="GOOGLE_GENAI_USE_VERTEXAI=1,VERTEX_PROJECT=$PROJECT,VERTEX_LOCATION=$LOC,VERTEX_MODEL=claude-sonnet-5,GCS_BUCKET=$BUCKET,ARTIFACT_SERVICE_URI=gs://$BUCKET"
```

Set `SESSION_SERVICE_URI=postgresql+asyncpg://…` for durable `DatabaseSessionService`; `ADK_WEB=1`
for the UI. Run locally the same way: `uvicorn main:app --port 8080`, then `adk web src` for the UI.

## 3. `adk deploy agent_engine` — Vertex AI **Agent Engine** (managed, ADK-native)

The managed runtime; no container/infra to run. Equivalent to the Python in
[`../deployment/deploy.py`](../deployment/deploy.py) (`AdkApp(agent=root_agent, enable_tracing=True)`
+ `agent_engines.create(requirements=[…], extra_packages=["./src"], env_vars=…)`), or the CLI:

```bash
adk deploy agent_engine --project=$PROJECT --region=$REGION \
  --staging_bucket=gs://$BUCKET src/testing_agent
# or:  python -m deployment.deploy --create --agent testing_agent
```

Best for the **autonomous `testing_agent`** (no MCP bridge). Changes the client contract (query via
the Agent Engine SDK: `remote.create_session(...)` + `remote.stream_query(...)`).

## 4. The hand-rolled Terraform ([`../../deployments/test-agent-v2`](../../deployments/test-agent-v2)) — A2A-only, **keeps the MCP bridge**

This is a **deliberate divergence** from paths 1–2. The agent sidecar runs `uvicorn <pkg>.adk_app:app`
where `adk_app.py` = `to_a2a(root_agent)` — serving **only the A2A protocol** (JSON-RPC `message/send`)
at `/`, behind the existing client-side **MCP bridge** (bridge :8080 → agent :8081). We use it because
the whole Testing-Agent UX is the MCP bridge + human confirm-gates (invariants I4/D2), and ADK's
native `/run` API is **not** what the bridge speaks. `adk deploy cloud_run` would serve the wrong API
and break the bridge — hence the custom Terraform.

---

## Which to use

| Consumer | Path |
|----------|------|
| **The existing MCP bridge / Claude Code** (gated KGA/TPD/evaluator) | **4 — the Terraform** (`to_a2a`, A2A). Required to keep the bridge (I4). |
| A standalone HTTP/`adk web` client, or a quick demo | **1 or 2** — `adk deploy cloud_run` / the `main.py` container (ADK REST API + optional UI). |
| The **autonomous `testing_agent`**, managed/no-ops | **3** — Agent Engine (`deployment/deploy.py`). |
| Any-of-the-above but also want A2A from the ADK server | path **2** with `a2a=True` (already set in `main.py`). |

**Bottom line:** paths 1–3 are the *canonical* ADK deploys (`adk deploy …` / `AdkApp`); path 4 is the
custom A2A-over-Cloud-Run deploy that preserves the MCP bridge. Both are real and both are here.
