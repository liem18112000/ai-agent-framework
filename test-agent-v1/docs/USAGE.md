# Using the Testing Agent with Claude

How to drive the **Testing Agent** from **Claude** (Claude Code or Claude Desktop). The agent is two
A2A services that share one GCS Memory Bank and are driven by local Claude:

- **Knowledge-Gathering** (`knowledge-gathering`) — Steps 1–2: crawl Jira/Confluence read-only, then
  refine into a confirmed understanding + insights (the "Collect insight" hand-off).
- **Test-Plan Definition** (`test-plan-definition`) — Steps 3–4: reconfirm a Test Plan
  (methodology/scope/metrics), then generate the test data / scenarios / steps.

Claude speaks **MCP**; each agent speaks **A2A**; an **A2A→MCP bridge** per agent translates — so from
Claude's side each agent is just a set of MCP tools. A single **`context_id`** threads the whole
pipeline: `gather_knowledge` mints it, and every later tool reuses it.

> Diagrams — end-to-end flow: [`agents-overview-flow.excalidraw`](./agents-overview-flow.excalidraw) ·
> software architecture: [`agents-software-architecture.excalidraw`](./agents-software-architecture.excalidraw) ·
> swimlane / sequence detail: [`agents-swimlane-detail.excalidraw`](./agents-swimlane-detail.excalidraw) ·
> full pipeline: [`full-flow.excalidraw`](./full-flow.excalidraw) · framework choice
> (ADK vs `a2a-sdk`-direct): [`adk-vs-current-stack.excalidraw`](./adk-vs-current-stack.excalidraw)

```
 Steps 1–2
   Claude ──MCP(Bearer) /mcp──▶ knowledge-gathering-agent ──┬──▶ Atlassian (Jira/Confluence, read-only)
                                (one Cloud Run service:      └──▶ Vertex AI (Claude generators)
                                 MCP bridge + A2A agent)

 Steps 3–4
   Claude ──MCP(Bearer) /mcp──▶ test-plan-definition-agent ─────▶ Vertex AI (Claude generators)
                                (one Cloud Run service:
                                 MCP bridge + A2A agent)

 Shared  GCS Memory Bank  gs://mt-receive-ai-agent-memory/memory/  ◀── read+written by both
         (notes/index/runs · refine/ · test-plan/)
```

Pipeline: `gather → refine → approve → define → approve → implement → (Test execution)`.

---

## 1. Connect Claude to the agents

Each agent runs as a single **bearer-gated** Cloud Run service that serves both its A2A API and its
MCP endpoint at `/mcp`. Register both once as remote MCP servers.

**Quickest — run the installer.** It reads the bearer tokens from `test-agent/.env`, resolves the
live `/mcp` URLs from `terraform output`, and registers both servers (re-runnable / idempotent):

```bash
test-agent/tools/install-mcp.sh               # macOS / Linux / Git Bash
test-agent/tools/install-mcp.sh --scope user  # register for every project, not just this one
```
```cmd
test-agent\tools\install-mcp.cmd              :: Windows CMD
```

**Or by hand.** The tokens live in Secret Manager and in `test-agent/.env` — never paste the values
into a committed file:

```bash
# values come from your .env / Secret Manager, not hard-coded
source test-agent/.env    # loads KGA_BRIDGE_BEARER_TOKEN, TPD_BRIDGE_BEARER_TOKEN

# Steps 1–2 — knowledge gathering + refinement
claude mcp add --transport http knowledge-gathering \
  https://knowledge-gathering-agent-q5rqhzn2uq-oa.a.run.app/mcp \
  --header "Authorization: Bearer $KGA_BRIDGE_BEARER_TOKEN"

# Steps 3–4 — test plan define + implement
claude mcp add --transport http test-plan-definition \
  https://test-plan-definition-agent-q5rqhzn2uq-oa.a.run.app/mcp \
  --header "Authorization: Bearer $TPD_BRIDGE_BEARER_TOKEN"
```

> The `/mcp` hostnames above are the current deployment; the installer avoids hard-coding them by
> reading `terraform output -raw bridge_url` / `tpd_bridge_url` from `deployments/`.

Then **restart Claude Code** so it loads the servers, and confirm:

```bash
claude mcp get knowledge-gathering      # Status: ✔ Connected
claude mcp get test-plan-definition     # Status: ✔ Connected
```

*(Claude Desktop: add the same URLs + headers as custom connectors.)*

**No client setup needed beyond connecting the servers.** The "test `<JIRA>`" trigger ships in the
MCP servers themselves — each bridge carries it in its `instructions` (so free-text
"test LUZ-158390" is recognized) and registers a server-provided **`test` prompt** (surfaces as
`/mcp__…__test`). A fresh Claude that has only added these two MCP servers can run the whole
pipeline — no `CLAUDE.md`, no slash-command files.

**Local dev (no Cloud Run):** run an agent + its bridge yourself.
```bash
uvicorn knowledge_gathering.server:app --port 8080         # KGA agent (A2A)
uvicorn test_plan_definition.server:app --port 8081        # TPD agent (A2A)
# bridges: stdio (Claude launches them) or HTTP —
TPD_BRIDGE_TRANSPORT=http TPD_A2A_URL=http://localhost:8081/ PORT=8090 \
  python -m test_plan_definition.bridge                    # TPD bridge at :8090/mcp
```

---

## 2. Tools Claude can call

### 2a. Knowledge-Gathering (Steps 1–2)

| Tool | Signature | What it does |
|------|-----------|--------------|
| `gather_knowledge` | `(seed, depth=2, context_id?)` | Crawl a Jira issue / Confluence page / URL read-only and distill it to the Memory Bank. Returns a **`context_id`** to reuse everywhere downstream. |
| `refine` | `(context_id, answer?)` | Multi-turn interrogation (business → technical → QA). Call once for a question round; answer each with `answer="Q-…: choice"` until it reports **Refinement complete**. |
| `approve` | `(context_id)` | Close the refine loop once *you* are satisfied — returns the confirmed understanding + Q&A as the "Collect insight" hand-off. |
| `get_questions` / `get_understanding` | `(context_id)` | Read the current questions / restated understanding (read-only). |
| `agent_card` | `()` | The agent's name, version, advertised skills. |
| `send_raw` | `(text, context_id?, task_id?)` | Escape hatch: arbitrary A2A message. |

### 2b. Test-Plan Definition (Steps 3–4)

| Tool | Signature | What it does |
|------|-----------|--------------|
| `define_plan` | `(context_id, answer?)` | Multi-turn reconfirm over **methodology → scope → metrics**. Answer each round with `answer="Q-mth-1: …"` until it reports **Plan definition complete**. |
| `get_plan` | `(context_id)` | Read the current Test Plan brief (read-only). |
| `approve_plan` | `(context_id)` | The reconfirm gate — lock `status=confirmed` so implement may run, and close the session. |
| `implement_plan` | `(context_id)` | One-shot: generate test data + scenarios (happy/negative) + steps, export a `.feature`. Refuses a draft plan. |
| `get_scenarios` | `(context_id)` | Read the generated scenarios + steps (read-only). |
| `plan_card` | `()` | The agent's name, version, advertised skills. |
| `send_raw` | `(text, context_id?, task_id?)` | Escape hatch: arbitrary A2A message. |

---

## 3. A typical end-to-end session

Both loops are **driven by Claude** — it keeps answering/reconfirming until *it* approves. The same
`context_id` flows from the first step to the last.

1. **Gather** — give Claude a seed:
   > "Gather knowledge for `LUZ-158390` at depth 2."

   `gather_knowledge("LUZ-158390", depth=2)` → a summary and a `context_id` (e.g. `run-6f2a`). Every
   link (description, comments, remote links, issue links, attachments) is recorded; out-of-scope
   links noted, unreachable ones flagged as gaps.

2. **Refine** — interrogate until confident:
   > "Refine `run-6f2a`."

   `refine("run-6f2a")` → business → technical → QA rounds; answer each
   (`refine("run-6f2a", answer="Q-biz-1: Fully materialized")`) until **Refinement complete**.

3. **Approve (knowledge)** — close the loop:
   > "That understanding is right — approve `run-6f2a`."

   `approve("run-6f2a")` → the confirmed understanding + Q&A (the "Collect insight" hand-off).

4. **Define** — reconfirm the Test Plan for the same context:
   > "Define the test plan for `run-6f2a`."

   `define_plan("run-6f2a")` → **methodology** round, then **scope**, then **metrics**; answer each
   (`define_plan("run-6f2a", answer="Q-mth-1: API")`) until **Plan definition complete**.
   `get_plan("run-6f2a")` shows the brief.

5. **Approve (plan)** — lock it:
   > "That plan is right — approve `run-6f2a`."

   `approve_plan("run-6f2a")` → `status=confirmed`.

6. **Implement** — generate the artifacts:
   > "Implement the plan for `run-6f2a`."

   `implement_plan("run-6f2a")` → test data + happy/negative scenarios + steps + an exported
   `.feature`. `get_scenarios("run-6f2a")` shows them; hand off to `story-to-bdd-scenarios` /
   `write-acceptance-tests` / `implement-bdd-steps` for richer BDD.

---

## 4. Where the output goes — the shared Memory Bank

Everything is persisted to GCS (`gs://mt-receive-ai-agent-memory/memory/`) so the next run starts
warm. Each stage writes its **own prefix**, so a later run never clobbers an earlier one that shares
the same `context_id`:

```
memory/
├── index/     knowledge-index.md · knowledge-index.json   (node + edge graph — incl. test-plan/scenario nodes)
├── notes/     jira/<KEY>.md · confluence/<id>.md · insight/<id>.md
├── refine/<context_id>/       questions · answers · understanding.md · state    (Step 2)
├── test-plan/<context_id>/    plan.json/.md · plan-brief.md · decisions · state  (Step 3)
│                              test-data.json · scenarios.json/.md · steps.json    (Step 4)
│                              features/<context_id>.feature                       (BDD export)
└── runs/      <ts>_run-<id>.md · <ts>_refine-<id>.md · <ts>_plan-<id>.md          (run-logs)
```

Notes/decisions carry provenance frontmatter and are **curated, not raw dumps** — invent nothing, drop
nothing silently (a broken link is *flagged*, an unreachable source becomes a *declared gap*, an
unanswered question a *declared gap*). Scenarios trace back to the insight/note they cover.

---

## 5. Generators — heuristic vs Claude-on-Vertex

Every generation seam (gather distill, refine questions/understanding, define questions/brief,
implement scenarios) uses **Claude on Vertex when `VERTEX_PROJECT`/`VERTEX_LOCATION`/`VERTEX_MODEL`
are set**, and a deterministic **no-LLM heuristic otherwise** — so both agents run (and their tests
pass) with no credentials, and get sharper output once Vertex is configured. Test data and API
`request→assert` steps stay heuristic (mechanical). POC scope is **API-first**; E2E/UI are valid
methodology answers but their fine step detail is deferred.

---

## 6. Deploy

Terraform lives in [`../../deployments`](../../deployments):

- `main.tf` / `bridge.tf` — the knowledge-gathering agent + bridge, the shared memory bucket, the
  runtime SA, and the A2A/bridge bearer secrets.
- `test-plan-definition.tf` — the test-plan agent + bridge (same image, reused bucket / runtime SA /
  A2A bearer; own inbound bridge secret). Toggle with `deploy_test_plan`.

Flow: `deploy.sh` builds + pushes the image; add a version to each bridge's inbound secret
(`kga-bridge-bearer-token`, `kga-tpd-bridge-bearer-token`) out-of-band; `terraform apply`. The
`bridge_url` and `tpd_bridge_url` outputs are the MCP endpoints to register in §1. A private bridge
(`*_allow_unauthenticated=false`) is reachable through `deployments/proxy.sh` (a local
`gcloud run services proxy`) — register `http://localhost:8080/mcp` instead.

---

## 7. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `Status: ✘ Failed to connect` right after a bridge redeploy, or `Dynamic Client Registration rejected (HTTP 401)` | The client got stuck after the connection dropped. **Re-register** (`claude mcp remove … -s local` then `claude mcp add …`) to reset it. |
| Everything returns `401` | Wrong / missing bearer. Confirm the `--header` token matches the bridge's inbound secret (curl the `/mcp` endpoint with the header — a bare GET should return `400`, not `401`). |
| Tools don't appear in Claude | MCP servers load at **startup** — restart Claude Code after registering. |
| `implement_plan` says the plan is *draft* | Run `approve_plan(context_id)` first — the confirm gate is load-bearing. |
| Bridge is private (`*_allow_unauthenticated=false`) | Reach it through `deployments/proxy.sh` and register `http://localhost:8080/mcp`. |

---

## 8. Reference

| Thing | Value |
|-------|-------|
| KGA service (MCP + A2A) | `https://knowledge-gathering-agent-q5rqhzn2uq-oa.a.run.app` — MCP at `/mcp` (terraform `bridge_url`), A2A card at `/.well-known/agent-card.json` |
| TPD service (MCP + A2A) | `https://test-plan-definition-agent-q5rqhzn2uq-oa.a.run.app` — MCP at `/mcp` (terraform `tpd_bridge_url`), A2A card at `/.well-known/agent-card.json` |
| Inbound tokens (Claude → bridge) | secrets `kga-bridge-bearer-token` / `kga-tpd-bridge-bearer-token` · env `KGA_BRIDGE_BEARER_TOKEN` / `TPD_BRIDGE_BEARER_TOKEN` |
| Downstream token (bridge → agent) | secret `kga-a2a-bearer-token` / env `A2A_BEARER_TOKEN` (shared by both agents) |
| Memory bank | `gs://mt-receive-ai-agent-memory/memory/` |
| Deploy / proxy | `deployments/deploy.sh` · `deployments/proxy.sh` · `deployments/test-plan-definition.tf` |

Bridge internals and transports (stdio vs HTTP), Cloud Run topology, and auth notes:
[`../src/knowledge_gathering/bridge/README.md`](../src/knowledge_gathering/bridge/README.md).
Plan-stage sequence: [`agents-swimlane-detail.excalidraw`](./agents-swimlane-detail.excalidraw). Enhancement
research + roadmap: [`RESEARCH-agentic-qa-enhancements.md`](./RESEARCH-agentic-qa-enhancements.md).

---

## 9. Design note — why `a2a-sdk`-direct, and where ADK fits

Both agents are built **directly on `a2a-sdk`** (+ FastAPI + Claude-on-Vertex), not on an agent
framework. The reason is *shape*: KGA and TPD are **deterministic pipelines** — Python drives the
steps and the LLM is one call inside a fixed flow — so [Google ADK (`adk-python`)](https://github.com/google/adk-python)
would add a framework layer (and route Claude through a LiteLLM hop) while removing none of the real
work (the Atlassian crawl, ADF parsing, gherkin render). ADK is built on the *same* foundation this
stack already uses — `a2a-sdk` + MCP + Vertex — so it **wraps** the base, it doesn't replace it.

Adopt ADK **only** for an agent where the *LLM drives the tool loop* (decides the next tool call):
build just that one agent as an `LlmAgent`, expose it with `to_a2a()`, and it joins the existing
A2A/MCP mesh next to KGA/TPD — no rewrite. The natural candidate here is an LLM-driven
**interrogator** (the refine loop), with its own `MCPToolset` (codegraph · Atlassian).

The full comparison — layer-by-layer stacks, the decision, and the hybrid-mesh endpoint — is in
[`adk-vs-current-stack.excalidraw`](./adk-vs-current-stack.excalidraw):

![ADK vs a2a-sdk-direct — layer comparison, the decision, and the hybrid mesh](./adk-vs-current-stack.png)
