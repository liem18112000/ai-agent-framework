# 02 · Plan A — transfer the testing agents (KGA + TPD) to ADK

The main plan: re-host `knowledge-gathering` and `test-plan-definition` as ADK agent graphs on the
shared `common` engine, exposed over A2A behind the unchanged bridge. Read
[`01-mapping.md`](01-mapping.md) first — this doc applies those decisions per agent and lays out the
milestones.

**Guiding rule:** *keep the engine, replace the shell.* Every `common/{memory,learn,interrogate,llm,
atlassian,codegraph,extract}` module is reused unchanged; only the `a2a-sdk` shell and the state
plumbing are rewritten.

**Where this is built:** all new/rewritten code lands in **`test-agent-v2/`** (it starts empty); the
reused engine is lifted from **`test-agent-v1/`** (the current code). Package-relative paths below
(`common/…`, `src/knowledge_gathering/…`) are the v2 layout — the same package structure as v1. See
the README's *Paths & versions*.

---

## A.0 — Shared foundation (do once, both agents depend on it)

A small neutral substrate every ADK agent uses:

1. **Lift `build_bank()` out of `common/executor.py`** into `common/memory/factory.py` (SDK-free), so
   nothing `a2a`-coupled sits between an agent and its bank. (`01`, row 5b.)
2. **`common/adk/` package** (new, neutral):
   - `model.py` — `claude_llm()` → `LiteLlm("vertex_ai/claude-sonnet-5")` with thinking-disabled +
     max_tokens wired (`01` §7). One place, so every agent inherits the gotcha fixes.
   - `services.py` — build the ADK `Runner` services: `DatabaseSessionService` on `common/db.py`'s
     engine (fallback `InMemorySessionService` when no DB), optional `GcsArtifactService`.
   - `plugins.py` — `LearnDrainPlugin` (`before_run_callback` = `learn.drain` + `maybe_drain_index`,
     off-path) and `LessonRecallPlugin` (`before_model_callback` = inject grounded lessons). (`01` §6.)
   - `serve.py` — `serve(root_agent, required_env)`: `to_a2a(root_agent)` → wrap with
     `BearerAuthMiddleware` + `make_health_routes` → uvicorn. The one-line replacement for `server.py`.
   - `tools.py` — the reusable `FunctionTool`s: `search_memory`, `get_note`, `search_lessons`,
     `veto_lesson`, `recall_lessons`, `atlassian_*`, `build_codegraph`. Thin wrappers over the neutral
     engine, shared by both agents.
3. **Tool/skill parity check** — a tiny test asserting the `to_a2a`-generated AgentCard advertises the
   same skill ids the bridge/tests expect, so the bridge keeps working untouched.

Everything after A.0 is per-agent and independently shippable behind the same bridge URL.

---

## A.1 — knowledge-gathering (KGA)

### Target agent graph

```
kga_root  = SequentialAgent? No — KGA has two independent entry skills, so use a thin dispatcher:
kga_root  (custom BaseAgent "KgaRouter", or two skills on one card)
├── gather skill  ──▶ GatherAgent            (custom BaseAgent — wraps the crawl engine)
│                     └── tools: atlassian_*, build_codegraph, (memory upsert)
├── refine skill  ──▶ RefineAgent            (custom BaseAgent — round loop, checkpoints to state)
│                     ├── QuestionGenAgent   (LlmAgent, output_schema=Questions)   ← 1 call/round
│                     └── UnderstandingAgent (LlmAgent, output_schema=Understanding) ← 1 call finalize
└── read skills ──▶ FunctionTools: search_memory, get_note, search_lessons, veto_lesson
```

**Design notes**
- **`GatherAgent` is a custom `BaseAgent`.** Its `_run_async_impl` calls the *existing*
  `run_gather` → `expansion_round()` → `crawl()` pipeline (offloaded via `asyncio.to_thread`) and
  `yield`s progress + a final summary `Event`. The BFS, budgets, fetchers, B0–B6, self-explore loop,
  GCS upserts — **all unchanged**. We are re-triggering, not rewriting. The two optional LLM fan-out
  tiers (G2 hypothesize, G4 leads) stay internal one-shot `complete()` calls behind their existing
  flags (they are leaves, not agent steps).
- **`RefineAgent` uses Option B (state checkpoint)** from [`01` §4]: it loads/advances the
  `common/interrogate` `RefineSession` but persists the loop state to **ADK session `state`** instead
  of GCS `state.json`, emits the rendered question round, and ends the invocation; the next turn
  reads state back and ingests the answer. The round strategies (`round/{business,technical,qa}.py`)
  and answer ingest/insight distillation are unchanged.
- **`QuestionGenAgent` / `UnderstandingAgent` are `LlmAgent`s** with `output_schema`, replacing the
  bespoke `make_generator()`/`make_understander()` selection — but **keep the heuristic fallback**:
  if the LlmAgent yields zero parseable questions, fall back to `heuristic_questions` (never a blank
  round). Wire the fallback as an `after_model_callback` or a post-step in `RefineAgent`.
- **Gather↔Refine re-seed edge** (`[seed:<node>]` answer → re-crawl) becomes `RefineAgent` invoking
  `GatherAgent` as a sub-agent / `AgentTool`, then reloading the run-scoped pack. Deduped as today.

### KGA milestones

| ID | Milestone | Test gate |
|----|-----------|-----------|
| A1-a | `GatherAgent` (BaseAgent wrapping `crawl`) + read-skill FunctionTools, on `InMemorySessionService`; `to_a2a` app served locally | offline harness: same nodes/tiers/gaps as today for `eval_rich`/`eval_thin`/`eval_bleed` fixtures |
| A1-b | `RefineAgent` round loop on ADK session state (Option B); QuestionGen/Understanding as LlmAgent + heuristic fallback | refine over recorded fixtures → same questions/understanding shape; leak stays out (B0) |
| A1-c | Swap to `DatabaseSessionService`; `LearnDrainPlugin` + `LessonRecallPlugin` wired | multi-turn refine survives a simulated instance restart; lesson recall grounded + `scope='shared'` only |
| A1-d | Deploy the KGA **agent container** on `to_a2a` app (bridge unchanged); parity smoke test through the real MCP bridge | live gather→refine→approve for a real ticket == pre-migration output |

---

## A.2 — test-plan-definition (TPD)

### Target agent graph

```
tpd_root (custom BaseAgent "TpdRouter", or skills on one card)
├── define skill    ──▶ DefineAgent    (custom BaseAgent — round loop, state checkpoint)
│                        ├── QuestionGenAgent  (LlmAgent, output_schema)  ← ≤3 calls (1/round)
│                        └── BriefAgent        (LlmAgent, output_schema)  ← 1 call at finalize
├── approve skill   ──▶ FunctionTool approve_plan            (deterministic: flip status→CONFIRMED)
├── implement skill ──▶ ImplementAgent (custom BaseAgent — wraps implement_plan)
│                        └── ScenariosAgent    (LlmAgent, output_schema)  ← the 1 default LLM call
│                        └── (test-data + steps LlmAgents — gated behind detail/TPD_LLM_DETAIL)
└── read skills   ──▶ FunctionTools: get_plan, get_scenarios
```

**Design notes**
- **`DefineAgent` mirrors `RefineAgent`** — the *same* `common/interrogate` engine, TPD's rounds
  (`methodology/scope/metrics`), Option-B state checkpoint. The two interrogation agents should share
  a single `InterrogationAgent` base parameterized by round set + generator/understander — one class,
  two configs. This is where the "shared engine" pays off twice.
- **`ImplementAgent` is a custom `BaseAgent`** wrapping the existing `implement_plan()` inside
  `asyncio.to_thread` (preserving the Cloud-Run-timeout mitigation). It orchestrates:
  `ScenariosAgent` (LlmAgent, the one always-on call) → deterministic coverage-matrix fallback → step
  generation (heuristic by default; LlmAgent only when `detail`/`TPD_LLM_DETAIL`) → `.feature` render
  (`render/gherkin.py`, unchanged) → GCS persist + graph provenance + pgvector project.
- **Preserve the `TPD_LLM_DETAIL` gate exactly.** Default `implement` = **one** LLM call
  (scenarios); test-data + steps stay heuristic unless `detail`. The whole `implement` still runs
  off the event loop. Do **not** let the ADK rewrite quietly turn three LlmAgents on by default — that
  reintroduces the `ERROR_TIMEOUT` incident.
- **`approve_plan` is a plain `FunctionTool`** — deterministic status flip + close the session; no LLM.
- **Consuming the KGA pack** is unchanged: `load_plan_pack(bank, ctx)` reads what KGA persisted under
  the same `context_id` (now the same `session_id`). No re-fetch from Atlassian.

### TPD milestones

| ID | Milestone | Test gate |
|----|-----------|-----------|
| A2-a | `InterrogationAgent` base extracted; `DefineAgent` on it (Option B); QuestionGen/Brief LlmAgents + fallback | define over `plan_*` fixtures → same brief/decisions shape; scope leak stays out (B0) |
| A2-b | `ImplementAgent` wrapping `implement_plan`; `ScenariosAgent` LlmAgent; detail-gate preserved | `implement` default = 1 LLM call; scenarios/steps/`.feature` byte-comparable to today for a fixture pack |
| A2-c | `DatabaseSessionService` + plugins; deploy TPD agent container on `to_a2a`; parity smoke test through the bridge | live define→approve→implement→get_scenarios == pre-migration; latency within Cloud Run timeout |

---

## A.3 — Deployment (mostly unchanged)

The v2 deployment is a copy of `deployments/test-agent-v1/` into **`deployments/test-agent-v2/`**
(same terraform, own state). The Cloud Run **sidecar topology, Cloud SQL, GCS bucket, secrets, IAM,
`/livez`/`/readyz`, and the bridge container are all unchanged.** The only edits:

- **Agent container start command**: `uvicorn <pkg>.server:app` → the `to_a2a` app (e.g.
  `uvicorn <pkg>.adk_app:app` or `adk`'s server entrypoint). Same port `:8081`, same probes.
- **Dockerfile**: add `google-adk` (and `litellm`) to the runtime deps (today it's only in the `eval`
  extra). One image still runs either the bridge or the agent.
- **`DatabaseSessionService`** needs the same Cloud SQL env the task store already gets — no new infra;
  the A2A `DatabaseTaskStore` env is repurposed. (The `deploy_cloudsql` toggle stays.)
- **Session affinity / `min=max=1`**: with a `DatabaseSessionService`, session state is no longer
  bridge-memory-bound on the *agent* side, but the **bridge still holds the MCP session in memory**,
  so keep `session_affinity` + single warm instance until the bridge is revisited (out of scope).
- **Rollback** is per-agent: revert the one agent container's start command + image tag; the bridge,
  the other agents, and all data are untouched. See [`04`](04-roadmap-risks.md).

## A.4 — What explicitly does *not* change

- The MCP tool names/signatures and the `test` prompt (bridge unchanged).
- The GCS memory-bank layout, the link-graph index CAS semantics, the pgvector schema, `MEMORY_BACKEND`.
- The B0–B6 de-bias gates and the lesson loop (only their *triggers* move to plugins).
- The deterministic pipeline and the single-LLM-call `implement` default.
- Claude Sonnet 5 as the model (now via LiteLlm).

## A.5 — Acceptance criteria for "Plan A done"

1. Both agents run as ADK agent graphs, served by `to_a2a`, behind the unchanged bridge.
2. The full offline eval harness passes with outputs **equivalent** to pre-migration (same nodes,
   same leak-gate results, same scenario/`.feature` shapes) — the evaluator (Plan B) is the judge.
3. Multi-turn refine/define survive an instance restart via `DatabaseSessionService`.
4. `implement` default is one LLM call and stays within the Cloud Run request timeout.
5. B0–B6 verified: no hard-negative leak in a bleed-fixture run; recalled lessons are grounded and
   `scope='shared'` only.
