# Using the Testing Agent (v2 / ADK) from local Claude

How to **install** and **drive** the ADK Testing Agent from **local Claude** (Claude Code or Claude
Desktop). v2 is the ADK-native rebuild: instead of three per-agent MCP bridges, there is **one MCP
gateway** that Claude connects to, and it routes each tool call to the right agent over **A2A**.

- **You (Claude) connect to ONE endpoint** — the `mcp-gateway-v2` service, registered as the MCP
  server named **`testing-agent`**. It exposes the union of every agent's tools.
- Behind it sit **three A2A-only agents**, each the same image with a different `AGENT` env:
  - **knowledge-gathering** (`knowledge_gathering`) — Steps 1–2: crawl Jira/Confluence/Bitbucket
    read-only, then refine into a confirmed understanding + insights.
  - **test-plan-definition** (`test_plan_definition`) — Steps 3–4: reconfirm a Test Plan
    (methodology/scope/metrics), then generate test data / scenarios / steps + a `.feature`.
  - **test-evaluation** (`test_evaluation`) — optional read-only quality gates that score the pack
    and the plan (never block).

A single **`context_id`** threads the whole pipeline: `gather_knowledge` mints it and every later
tool reuses it.

```
Claude ──MCP/HTTPS (GATEWAY_BEARER)──▶ mcp-gateway-v2  ──┬── A2A (A2A_BEARER) ──▶ knowledge-gathering-agent-v2
   (one server: "testing-agent")   (routes each tool     ├──────────────────────▶ test-plan-definition-agent-v2
                                    call over A2A)        └──────────────────────▶ test-evaluation-agent-v2

Shared  GCS Memory Bank  gs://<project>-kga-v2-memory/memory/   ◀── read+written by all three
        Durable sessions/tasks  Cloud SQL Postgres (kga-v2-taskstore, DatabaseSessionService)
```

Pipeline:
`gather_knowledge → refine → approve → [evaluate_pack] → define_plan → approve_plan → implement_plan → get_scenarios → [evaluate_plan]`

> Target-architecture diagram: [`DESIGN-mcp-gateway-target.png`](./DESIGN-mcp-gateway-target.png)
> (source [`DESIGN-mcp-gateway-target.excalidraw`](./DESIGN-mcp-gateway-target.excalidraw)). Design
> rationale: [`DESIGN-mcp-gateway.md`](./DESIGN-mcp-gateway.md). Deploy paths: [`DEPLOY.md`](./DEPLOY.md).

---

## 1. Install — connect Claude to the gateway

The gateway is a bearer-gated Cloud Run service serving Streamable-HTTP MCP at `/mcp`. You register
**one** server (v2 is a single endpoint).

**Quickest — run the installer.** It reads `GATEWAY_BEARER_TOKEN` from `test-agent-v2/.env`, resolves
the live `/mcp` URL from `terraform output -raw gateway_url`, and registers the one server
(idempotent / re-runnable):

```bash
cd deployments/test-agent-v2
./install-mcp.sh                 # scope: local (current project)
./install-mcp.sh --scope user    # available in every project
```
```cmd
cd deployments\test-agent-v2
install-mcp.cmd                  :: Windows CMD
install-mcp.cmd --scope user
```

**Or by hand.** The token lives in `test-agent-v2/.env` / Secret Manager — never paste the value into
a committed file:

```bash
cd deployments/test-agent-v2
claude mcp add --transport http testing-agent "$(terraform output -raw gateway_url)" \
  --header "Authorization: Bearer $GATEWAY_BEARER_TOKEN"
```

Then **restart Claude Code** so it loads the server, and confirm:

```bash
claude mcp get testing-agent      # Status: ✔ Connected
```

*(Claude Desktop: add the same URL + header as a custom connector.)*

**No client setup needed beyond connecting the server.** The `test <JIRA>` trigger ships **inside the
gateway** — it carries the trigger in its `instructions` (so free-text "test LUZ-158390" is
recognized) and registers a server-provided **`test` prompt** (surfaces as
`/mcp__testing-agent__test`). A fresh Claude that has only added this one MCP server can run the whole
pipeline — no `CLAUDE.md`, no slash-command files.

**Private gateway.** If deployed with `bridge_allow_unauthenticated=false`, the gateway isn't
publicly reachable; run `deployments/test-agent-v2/proxy.sh` (a local `gcloud run services proxy`) and
register `http://localhost:8080/mcp` instead.

### Local dev (no Cloud Run)

Run the three agents over A2A, then point the gateway at them. Each agent is the **same** `main:app`,
selected by the `AGENT` env:

```bash
cd test-agent-v2
AGENT=knowledge_gathering   uvicorn main:app --port 8081 &
AGENT=test_plan_definition  uvicorn main:app --port 8082 &
AGENT=test_evaluation       uvicorn main:app --port 8083 &

# Gateway over HTTP (defaults already point at :8081/:8082/:8083):
GATEWAY_TRANSPORT=http PORT=8080 \
  KGA_A2A_URL=http://localhost:8081/ \
  TPD_A2A_URL=http://localhost:8082/ \
  TEV_A2A_URL=http://localhost:8083/ \
  python -m gateway                # gateway MCP at http://localhost:8080/mcp
```

Register `http://localhost:8080/mcp` (no bearer needed locally unless `GATEWAY_BEARER_TOKEN` is set).
Or launch the gateway as a **stdio** MCP server directly from Claude
(`claude mcp add testing-agent -- python -m gateway`, with the `*_A2A_URL` env), still with the three
agents running. With no `VERTEX_*` set, generators fall back to the no-LLM heuristic — everything
still runs.

---

## 2. Tools Claude can call (on the one `testing-agent` server)

All tools below are exposed by the gateway as `mcp__testing-agent__<tool>` and take/return the shared
`context_id`.

### 2a. Knowledge-Gathering (Steps 1–2)

| Tool | Signature | What it does |
|------|-----------|--------------|
| `gather_knowledge` | `(seed, depth=2, repo?, context_id?, exclude?)` | Crawl a Jira issue / Confluence page / URL read-only and distill it to the Memory Bank. Returns a **`context_id`** to reuse everywhere. `repo=` grounds the crawl in a Bitbucket code graph; `exclude=` prunes drift on a re-gather. |
| `gather_codebase` | `(repo, context_id?)` | Build a graphify code graph for a Bitbucket repo — code-base intelligence added to the pack. |
| `refine` | `(context_id, answer?)` | Multi-turn interrogation (business → technical → QA). Call once per round; answer each with `answer="Q-…: choice"` until **Refinement complete**. |
| `approve` | `(context_id)` | Close the refine loop once *you* are satisfied — returns the confirmed understanding + Q&A (the "Collect insight" hand-off). |
| `get_questions` / `get_understanding` | `(context_id)` | Read the current questions / restated understanding (read-only). |
| `search_memory` | `(query="")` | Search the knowledge index (link graph) in the GCS bank. |
| `get_note` | `(note_id)` | Read one distilled note, e.g. `get_note("jira:LUZ-158390")`. |
| `search_lessons` / `veto_lesson` | `(query="")` / `(insight_id)` | List captured self-learning lessons / retract a wrong one (excluded from recall, never re-learned). |

### 2b. Test-Plan Definition (Steps 3–4)

| Tool | Signature | What it does |
|------|-----------|--------------|
| `define_plan` | `(context_id, answer?)` | Multi-turn reconfirm over **methodology → scope → metrics**. Answer each round with `answer="Q-mth-1: …"` until **Plan definition complete**. |
| `get_plan` | `(context_id)` | Read the current Test Plan brief (read-only). |
| `approve_plan` | `(context_id)` | The reconfirm gate — lock `status=confirmed` so implement may run. |
| `implement_plan` | `(context_id, detail=False)` | One-shot: generate test data + scenarios (happy/negative) + steps, export a `.feature`. Refuses a draft plan. `detail=True` opts into the extra (slower) LLM detail pass. |
| `get_scenarios` | `(context_id)` | Read the generated scenarios + steps (read-only). |

### 2c. Test-Evaluation — optional quality gates (read-only, never block)

| Tool | Signature | What it does |
|------|-----------|--------------|
| `evaluate_pack` | `(context_id)` | Score the gathered+refined pack into a **Pack Quality Score** (retrieval recall/precision with a hard-negative leak gate + groundedness rubrics). |
| `evaluate_plan` | `(context_id)` | Score the test plan + suite into a **Test-Plan Score** (AC-coverage, matrix completeness, traceability). |
| `benchmark_run` | `(context_id, recompute=False)` | A run's cached **benchmark scorecard** — PQS + TPS + components, computed & saved (`memory/benchmarks/<ctx>.json`) if missing. Also auto-computed when `implement_plan` finishes (success *or* fail). |
| `compare_benchmarks` | `(context_ids)` | Two or more runs' benchmarks side by side (space/comma-separated ids) — per-metric table + delta. |
| `summarize_benchmarks` | `(k=5)` | The **K latest runs** (K<10) as a table + PQS/TPS mean/min/max/best-worst. |

Benchmarks read through an optional **cache** (`common/cache`): no-op by default, `CACHE_BACKEND=memory` locally, or GCP **Memorystore Redis** in prod (`deploy_redis=true`, wired to the test-evaluation service via a Serverless VPC connector). GCS stays the source of truth; a cache miss/outage just recomputes.

### 2d. Gateway meta / escape hatches

| Tool | Signature | What it does |
|------|-----------|--------------|
| `agent_cards` | `()` | Fetch all three agents' A2A cards (name, version, advertised skills). One unreachable agent doesn't hide the others. |
| `send_raw_kga` / `send_raw_tpd` / `send_raw_tev` | `(text, context_id?, task_id?)` | Escape hatch: send an arbitrary A2A message to one agent; returns reply + ids + state. |
| `test` (prompt) | `(jira_key, depth=2)` | `/mcp__testing-agent__test` — the full interactive pipeline for one ticket. |

### 2e. `[ADMIN — non-pipeline]` — memory & history operator utility

Served by the separate **`admin_agent`** service; **not** part of `gather → … → implement`. Read /
reset / snapshot the Memory Bank; never call these as a pipeline step.

| Tool | Signature | What it does |
|------|-----------|--------------|
| `list_runs` | `(limit=50)` | List every past run (one per `context_id`), newest first — seed, refine status, Q&A/pack/lesson counts. |
| `get_run` | `(context_id)` | Full structured detail for one run: understanding, Q&A, pack, plan/scenarios/coverage, run logs, lessons. |
| `view_memory` | `(tier="all", context_id?)` | View the four memory tiers `all\|working\|episodic\|semantic\|procedural`. `working` needs a `context_id`. |
| `backup_memory` | `(summary)` | Snapshot the bank to `memory-backups/<version>/` + a manifest (pgvector is rebuildable, not copied). |
| `list_backups` | `()` | List backup versions, newest first. |
| `wipe_all` | `(confirm)` | **DESTRUCTIVE** — clears the bank, pgvector, and the A2A task + ADK session tables in one call. `confirm` MUST equal the **GCS bucket name** (or the literal `"WIPE"` when unset); it refuses and echoes the exact token otherwise. `memory-backups/**` always survives. Ask the user **Yes/No** first. |

---

## 3. The confirm gates are YOURS (client-owned)

The tools **do not** prompt on their own (server-driven MCP elicitation was removed — Claude Code
can't deliver it over remote HTTP, issue #85442). **You** own every gate: before each of **`refine`**,
**`approve`**, **`define_plan`**, **`approve_plan`**, and **`implement_plan`**, ask the user a **Yes/No**
via the interactive question dialog and call the tool only on *yes* — never auto-approve. For each
per-round question an interrogation returns, present the options + the agent's recommendation and let
the user pick before submitting the next `answer=`.

`evaluate_pack` / `evaluate_plan` are read-only — surface the score, but they never block.

**Fan out the read-only steps.** The gated stages are sequential (one `context_id`, a human gate
before each), but reads are not: when you must read many Memory-Bank nodes at once (a `get_note` sweep
over a large pack, a `search_memory` / `get_understanding` sweep), run them in **parallel** across
concurrent read-only subagents (~5 node ids each, compact per-node summaries) to cut wall-clock and
keep large note bodies out of the driver's context. Never parallelize a stateful gated stage or two
ops on the same `context_id`.

---

## 4. A typical end-to-end session

The fastest path: just say **"test LUZ-158390"** (or run `/mcp__testing-agent__test`). Claude runs the
whole pipeline interactively, pausing at each gate. The manual walkthrough — the same `context_id`
flows from the first step to the last:

1. **Gather** — *"Gather knowledge for `LUZ-158390` at depth 2."*
   `gather_knowledge("LUZ-158390", depth=2)` → a summary and a `context_id` (e.g. `run-6f2a`). Every
   link (description, comments, remote/issue links, attachments, parent/subtasks, commits, PRs) is
   recorded; out-of-scope links noted, unreachable ones flagged as gaps. (Ground it in code with
   `repo="luz_finance"` when a repo is recommended.)

2. **Refine** — *"Refine `run-6f2a`."* (ask Yes/No first)
   `refine("run-6f2a")` → business → technical → QA rounds; show each round's options + recommendation,
   then `refine("run-6f2a", answer="Q-biz-1: Fully materialized")`, until **Refinement complete**.

3. **Approve (knowledge)** — *"That understanding is right — approve `run-6f2a`."*
   `approve("run-6f2a")` → the confirmed understanding + Q&A (the "Collect insight" hand-off).

4. **Evaluate the pack (optional)** — `evaluate_pack("run-6f2a")` → the Pack Quality Score + retrieval/
   rubric breakdown. If it flags a bleed (leaked hard-negatives) or low recall, offer to **re-gather**
   (`exclude=…` / `repo=…`, a fresh `context_id`) before planning. Read-only; never blocks.

5. **Define** — *"Define the test plan for `run-6f2a`."* (ask Yes/No first)
   `define_plan("run-6f2a")` → **methodology** → **scope** → **metrics**; answer each
   (`define_plan("run-6f2a", answer="Q-mth-1: API")`) until **Plan definition complete**.
   `get_plan("run-6f2a")` shows the brief; ask the user to confirm it.

6. **Approve (plan)** — *"That plan is right — approve `run-6f2a`."*
   `approve_plan("run-6f2a")` → `status=confirmed`.

7. **Implement** — *"Implement the plan for `run-6f2a`."*
   `implement_plan("run-6f2a")` → test data + happy/negative scenarios + steps + an exported
   `.feature`. `get_scenarios("run-6f2a")` shows them.

8. **Render the deliverable** — render the returned scenarios into a **single self-contained,
   versioned HTML artifact** (render the agent's output; don't author scenarios freehand). Optionally
   `evaluate_plan("run-6f2a")` for the Test-Plan Score. Hand off to `story-to-bdd-scenarios` /
   `write-acceptance-tests` / `implement-bdd-steps` for richer BDD.

---

## 5. Where the output goes — the shared Memory Bank

Everything persists to GCS (`gs://<project>-kga-v2-memory/memory/`, v2's own bucket) so the next run starts warm. Each stage writes its **own prefix** keyed by `context_id`:

```
memory/
├── index/     knowledge-index.md · knowledge-index.json   (node + edge graph — incl. plan/scenario nodes)
├── notes/     jira/<KEY>.md · confluence/<id>.md · insight/<id>.md · lesson/<id>.md
├── refine/<context_id>/       questions · answers · understanding.md · state    (Step 2)
├── test-plan/<context_id>/    plan.json/.md · plan-brief.md · decisions · state  (Step 3)
│                              test-data.json · scenarios.json/.md · steps.json    (Step 4)
│                              features/<context_id>.feature                       (BDD export)
└── runs/      <ts>_run-<id>.md · <ts>_refine-<id>.md · <ts>_plan-<id>.md          (run-logs)
```

Durable **sessions/tasks** live in Cloud SQL Postgres (`kga-v2-taskstore`, ADK's
`DatabaseSessionService`) — surviving Cloud Run revisions. Notes are curated, not raw dumps: a broken
link is *flagged*, an unreachable source becomes a *declared gap*, an unanswered question a *declared
gap*. Scenarios trace back to the insight/note they cover.

---

## 6. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `Status: ✘ Failed to connect` right after a redeploy, or `Dynamic Client Registration rejected (HTTP 401)` | The client got stuck after the connection dropped. **Re-register** (`claude mcp remove testing-agent -s local`, then `install-mcp`) to reset it. |
| Everything returns `401` | Wrong / missing bearer. Confirm `--header` matches `GATEWAY_BEARER_TOKEN`. (A bare GET on `/mcp` with the header should return `400`, not `401`.) |
| Tools don't appear in Claude | MCP servers load at **startup** — restart Claude Code after registering. |
| `gather_knowledge` returns `isError` / "malformed response" | Agent OOM during crawl. v2 agents run at **2Gi** (fixed in tf); if you lowered it, restore the `memory` default. |
| `implement_plan` says the plan is *draft* | Run `approve_plan(context_id)` first — the confirm gate is load-bearing. |
| `agent_cards` shows one agent "unreachable" | That agent's Cloud Run service is down / mis-URL'd. Check `terraform output kga_a2a_url` / `tpd_a2a_url` / `tev_a2a_url` and the service health (`/livez`, `/readyz`). |
| `gather_knowledge(repo=…)` aborts mid-build | The inline graph build can exceed Claude Code's default 300s MCP idle timeout — raise `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT`, or pre-build the graph, or gather without `repo=` then `gather_codebase`. |
| Codegraph returns a gap | Wrong repo slug (404) or missing Bitbucket creds. Verify the slug; ensure `ATLASSIAN_BITBUCKET_*` secrets are wired. |

---

## 7. Reference

| Thing | Value |
|-------|-------|
| MCP server to register | `testing-agent` → `$(terraform output -raw gateway_url)` (= `<gateway_service_url>/mcp`) |
| Gateway service | `mcp-gateway-v2` — MCP at `/mcp`, `/livez` · `/readyz` |
| Agent services (A2A-only) | `knowledge-gathering-agent-v2` · `test-plan-definition-agent-v2` · `test-evaluation-agent-v2` — A2A card at `/.well-known/agent-card.json` |
| Inbound token (Claude → gateway) | secret `kga-v2-gateway-bearer-token` · env `GATEWAY_BEARER_TOKEN` |
| Downstream token (gateway → agents) | secret `kga-v2-a2a-bearer-token` · env `A2A_BEARER_TOKEN` (shared by all three) |
| Memory bank | `gs://<project>-kga-v2-memory/memory/` |
| Session/task store | Cloud SQL Postgres `kga-v2-taskstore` (`deploy_cloudsql=true`, on by default) |
| Deploy / install / proxy | `deployments/test-agent-v2/deploy.sh` · `install-mcp.{sh,cmd}` · `proxy.sh` |

**Deploy in one line:** `cd deployments/test-agent-v2 && ./deploy.sh && ./install-mcp.sh`. Full deploy
options (the three ADK deploy paths and why v2 keeps the gateway) are in [`DEPLOY.md`](./DEPLOY.md);
Terraform details in [`../../deployments/test-agent-v2/README.md`](../../deployments/test-agent-v2/README.md).
