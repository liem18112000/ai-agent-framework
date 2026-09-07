# 00 · Current state — the baseline we transform *from*

A faithful snapshot of the Testing Agent stack today, so the plans that follow are self-contained.
Everything here is grounded in the code as of this branch; file paths are relative to
`test-agent-v1/` (the current a2a-sdk code — the ADK build lands in `test-agent-v2/`; see the
README's *Paths & versions*).

---

## 1. Runtime topology

```
Claude Code ──MCP(stdio│HTTP)──▶ MCP bridge ──A2A(JSON-RPC/HTTP)──▶ A2A agent ──▶ GCS bank + Cloud SQL
 (client/orchestrator)           (client-side)                     (Cloud Run)      (memory + tasks)
```

- **Three A2A agents**, each a FastAPI + `a2a-sdk` JSON-RPC service:
  `knowledge-gathering` (KGA), `test-plan-definition` (TPD), `test-evaluation` (evaluator).
- **Client-side MCP bridges** translate each MCP tool call → an A2A `message/send`. Claude Code
  only ever speaks MCP; it never sees A2A.
- **Cloud Run sidecar topology** (one service per agent, two containers on one image):
  `bridge` container (ingress `:8080`, serves `/mcp`, is the A2A *client*) + `agent` sidecar (A2A
  server on `localhost:8081`, never internet-exposed). Session state lives in the bridge's memory →
  each service pins to one warm instance (`session_affinity`, `min=max=1`, `cpu_idle=false`).
- **Model**: Claude Sonnet 5 on Vertex, called **directly** through `anthropic[vertex]`
  (`common/llm/vertex.py`), *not* through any framework. `thinking` is disabled so the whole
  `max_tokens` budget goes to output.
- **Persistence**: a **GCS markdown memory bank** (the record/event-log) + an optional **Cloud SQL
  Postgres** instance that backs *both* the durable A2A `DatabaseTaskStore` *and* the pgvector recall
  tier (both dial the same instance via `common/db.py`).

## 2. The pipeline (what the agents actually do)

`gather → refine → approve → [evaluate_pack] → define → approve_plan → implement → get_scenarios →
render`. The client (Claude Code) owns every confirm gate (Yes/No before refine/approve/define/
approve_plan/implement); the agents never auto-advance.

## 3. The load-bearing fact: the pipeline is **deterministic**, the LLM is a leaf

Across all three agents, **Python drives the control flow**; the LLM is only ever a *single, bounded,
one-shot completion* that returns JSON (questions / scenarios / search terms) or short prose
(understanding / brief / synopsis), always with a **heuristic fallback**. No agent contains a loop
where the model decides the next tool call. The master gate is `vertex_config()` — if the Vertex env
is unset, **every** agent runs fully deterministic with zero LLM calls.

### KGA — LLM-vs-deterministic

| Flow | Shape | LLM calls (default prod) |
|------|-------|--------------------------|
| **gather** | pre-crawl fan-out (`explore/expand.py`: hypothesize→climb→self-seed→Atlassian-search→leads-gate) then a **bounded BFS crawl** (`loop/crawl.py`, ≤40 nodes / 180–600 s, concurrency 8) with per-kind fetchers (jira/confluence/bitbucket/web/codegraph). 100% Python-driven. | **0** by default. Two fan-out tiers (G2 hypothesize, G4 leads) are single calls but flag-gated OFF. Node distill is wired to the **heuristic** in prod (the Claude distiller exists but isn't wired). |
| **refine** | multi-turn HITL interrogation over rounds `business/technical/qa`; pauses in A2A `input-required`, resumes next turn by rehydrating from GCS. | 1 bounded call per round for question-gen (when Vertex set) + 1 at finalize for the understanding brief; heuristic fallback for both. |
| memory reads | `search-memory`, `get-note`, `search-lessons`, `veto-lesson` | 0 (pure reads/writes). |

### TPD — LLM-vs-deterministic

| Flow | Shape | LLM calls (default prod) |
|------|-------|--------------------------|
| **define** | multi-turn HITL interrogation over rounds `methodology/scope/metrics`; same pause/resume as refine. Plan brief assembled once at finalize. | up to 3 question-gen calls (1/round) + 1 brief call, gated only by `vertex_config()`. **`TPD_LLM_DETAIL` does not affect define.** |
| **implement** | generate test-data → scenarios → Gherkin steps → render `.feature`. Whole thing runs in `asyncio.to_thread`. | **1** call by default (`scenarios`). test-data + steps are LLM **only** under `detail`/`TPD_LLM_DETAIL` (default OFF — the fix for the historical 3-serial-Vertex-call Cloud Run timeout). |
| reads | `get_plan`, `get_scenarios`, `approve_plan` | 0. |

### Evaluator — LLM-vs-deterministic

- `evaluate_pack(ctx)` → **PQS** and `evaluate_plan(ctx)` → **TPS**. Both read the other agents'
  persisted artifacts from the shared bank *as plain dicts* (never import KGA/TPD).
- **The shipped runtime PQS/TPS are 100% deterministic.** Composite = weighted mean of 5 components
  each. `trajectory` is left neutral (1.0) at runtime; the RAGAS / LLM-judge / semantic-rubric / noise
  / topic signals exist **only in the nightly `tests/eval/` judged tier and are never folded into the
  runtime score**.
- **`google-adk` is not imported anywhere** in `src/` or `tests/`. It is a pin in the `eval` extra +
  names in docstrings, card tags, and design docs. `trajectory.py` reimplements
  `tool_trajectory_avg_score` by hand; `ragas_judge.py` reimplements `hallucinations_v1`-intent via
  RAGAS. **ADK today is aspirational.**

## 4. State & persistence (the part that changes most)

Each A2A request is **stateless**; multi-turn continuity is reconstructed every turn:

- **Interrogation session state** (pending rounds, deferred/carried questions, answered set, insight
  ids, pass counter, `done` flag) is serialized to the **GCS bank** at
  `memory/{refine,test-plan}/<slug(ctx)>/state.json` and rehydrated each turn. A live (`done:false`)
  `state.json` is how the executor recognizes a continuation turn.
- **A2A conversation-id → pack-context-id** mapping is a second GCS file
  (`.../_sessions/<slug(a2a_ctx)>.json`).
- The **pack itself is never stored as a blob** — it is recomputed each turn by `load_pack()` from
  the global GCS index, **filtered to `run_id == context_id`** (this run-scoping is the **B0** de-bias).
- The **A2A `DatabaseTaskStore`** (Cloud SQL) persists only the A2A `Task` lifecycle
  (`input-required`/`completed`, message history) — *not* the domain session state.

So today there are **two** separate durability mechanisms (A2A tasks in Postgres + domain state in
GCS files). ADK's `SessionService` collapses these into one — see [`01-mapping.md`](01-mapping.md).

## 5. The de-bias gates (must survive the transfer)

Auto-recall of memory re-introduces the very biases the team fought (B0–B6). The mitigations live in
the framework-neutral layers and must be preserved verbatim:

- **B0** run-scoped pack (`interrogate/pack.py`, `run_id == context_id`).
- **B4** IDF hub-penalty on promotions (`memory/graph_index.py::rank_promotions`).
- **B5** structural grounding gate (`graph_index.graph_grounded` / `pg/store.py::grounded`) +
  semantic recall restricted to `scope='shared'`.
- **B1/B2/B3/B6** structural climb / codegraph anchor / topic-coherence stop / negative-signal prune
  (in `knowledge_gathering/explore/*`).
- **Lesson loop** (`common/learn/*`): capture→gate→persist→recall, flag-gated OFF by default; recall
  is grounded (B5), semantic arm `scope='shared'` only.

## 6. The clean seam — neutral core vs. framework shell

The codebase already draws the exact line the transfer needs (`src/common/__init__.py`: *"common is
the generic, agent-agnostic core; neither agent reaches into the other"*):

- **Framework-neutral (no `a2a`/`mcp`/`fastapi` import) — reusable as ADK tools/services as-is:**
  `common/memory/*` (incl. `pg/*`), `common/learn/*`, `common/interrogate/*` (incl. `round/*`),
  `common/llm/*` (incl. `distill/*`), `common/atlassian/*`, `common/extract/*`, `common/codegraph/*`,
  `common/models/*`, `common/db.py`, `common/monitoring.py`.
- **`a2a-sdk`-coupled — replaced under ADK:** each agent's `server.py` / `agent.py` / `executor/*`,
  plus `common/card.py`, `common/taskstore.py` (the `DatabaseTaskStore` wrapper only), `common/
  executor.py` (`reply`/`now`), `common/ops.py`, `common/middlewares/auth.py`, all of `common/bridge/*`.
- The **one cleanup**: `build_bank()` (SDK-free) currently lives in the `a2a`-importing
  `common/executor.py`; lift it into a neutral module so nothing framework-coupled sits between the
  agent and its bank.

This seam is why the transfer is tractable: **~70% of the code (the engine) doesn't move**; the
migration is concentrated in the ~30% shell.
