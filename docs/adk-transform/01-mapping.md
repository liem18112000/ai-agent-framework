# 01 · ADK primer + the master mapping

How each piece of today's stack maps onto ADK, and the cross-cutting design decisions that make the
transfer faithful. Version target: `google-adk ≥ 1.22` (`adk-python`). Where an API is
version-sensitive it is marked **[verify @1.22]**.

---

## 1. ADK in one screen (only the primitives we use)

- **`LlmAgent`** — a reasoning agent: a model + instructions + tools; can have `output_schema`/
  `output_key` to write a structured result into session **state**.
- **Workflow agents — deterministic orchestration, the LLM does *not* pick the next step:**
  - `SequentialAgent` — run sub-agents in a fixed order.
  - `LoopAgent` — repeat sub-agents until a sub-agent escalates / a max-iterations cap.
  - `ParallelAgent` — run sub-agents concurrently.
- **`BaseAgent`** — a custom agent: you implement `_run_async_impl(ctx)` and `yield Event`s. This is
  the escape hatch for "wrap existing Python and emit events" — the key to re-hosting the crawl/
  implement engines *verbatim*.
- **Tools** — `FunctionTool` (a Python callable), `LongRunningFunctionTool` (returns a *pending*
  result; the runner pauses; a later turn supplies the result — the **HITL** primitive),
  `AgentTool` (call one agent as a tool of another), `MCPToolset` (consume an external MCP server's
  tools). Tools receive a `ToolContext` (session state, artifacts, `request_confirmation()`).
- **`Runner` + services** — the runtime. Pluggable services: **`SessionService`**
  (`InMemory` / `DatabaseSessionService` / `VertexAiSessionService`) holds sessions + `state` +
  the event log; **`MemoryService`** (`InMemory` / `VertexAiRagMemoryService`) is long-term recall;
  **`ArtifactService`** (`InMemory` / `GcsArtifactService`) stores binary/rendered artifacts.
- **Callbacks & Plugins** — `before/after_{agent,model,tool}_callback` hooks; **Plugins**
  (`BasePlugin`) are the same hooks registered **globally** across every agent/tool/run — the
  natural home for cross-cutting "run on every request" logic.
- **A2A exposure** — **`to_a2a(agent, host, port, protocol, agent_card=None)`**
  (`google.adk.a2a.utils.agent_to_a2a`) returns an A2A ASGI app and **auto-generates the AgentCard**
  from the agent (skills/capabilities/metadata) unless you pass one. [verify @1.22]
- **Model routing** — `LiteLlm(model="vertex_ai/claude-sonnet-5")` for Claude on Vertex.
- **Evaluation** — `AgentEvaluator` + `adk eval`, `*.evalset.json` + `test_config.json`; metrics
  `tool_trajectory_avg_score`, `response_match_score`, `final_response_match_v2`, `safety_v1`,
  `hallucinations_v1`, `rubric_based_{tool_use,final_response}_quality_v1`; **custom metrics** via the
  metric registry. (Plan B's whole subject — see [`03`](03-plan-test-evaluation.md).)

Docs: <https://google.github.io/adk-docs/> · A2A: <https://google.github.io/adk-docs/a2a/quickstart-exposing/>
· eval: <https://google.github.io/adk-docs/evaluate/> · HITL long-running tools:
<https://google.github.io/adk-docs/tools-custom/function-tools/>.

---

## 2. Master component-mapping table

| # | Today | → ADK target | Kind |
|---|-------|--------------|------|
| 1 | `server.py` (FastAPI + `create_jsonrpc_routes` + `DefaultRequestHandler`) | `to_a2a(root_agent)` → ASGI app, served by uvicorn | **replace** |
| 2 | `common/card.py` (`build_agent_card`, `AgentSkill`s) | AgentCard **auto-generated** by `to_a2a` from the agent; or a hand-supplied `agent_card=` for exact skill text | **replace** |
| 3 | each `executor/base.py` (text-prefix router → handlers) | the **root agent graph** (a `SequentialAgent`/`LoopAgent`/`BaseAgent`); routing by explicit skills/tools, not string prefixes | **replace** |
| 4 | `common/taskstore.py` `DatabaseTaskStore` + the GCS `state.json` rehydration | **`DatabaseSessionService`** on the same `common/db.py` engine — one durable store for session + state + events | **replace (and unify 2→1)** |
| 5 | `common/executor.py` `reply()`, `now()` | ADK `Event`/`yield` + `ctx` timestamps | **replace** |
| 5b| `common/executor.py` `build_bank()` | move to a neutral module (`common/memory/factory.py`), call from an ADK service/tool init | **relocate** |
| 6 | `common/ops.py` `/livez` `/readyz` | mount the same Starlette routes on the `to_a2a` app (unchanged) | **reuse** |
| 7 | `common/middlewares/auth.py` `BearerAuthMiddleware` | wrap the `to_a2a` ASGI app with the same middleware | **reuse** |
| 8 | `common/bridge/*` (client-side MCP↔A2A bridge) | **unchanged** — still MCP↔A2A; the agent is still A2A behind it | **reuse (no change)** |
| 9 | `common/llm/vertex.py` `complete()` direct Anthropic | `LiteLlm("vertex_ai/claude-sonnet-5")` inside each `LlmAgent`; keep `complete()` for tool-internal one-shots | **wrap** |
| 10 | `common/interrogate/*` round engine + `round/*` | an **interrogation agent** (custom `BaseAgent` or `LoopAgent`) using the same round strategies as tools/logic; question-gen becomes an `LlmAgent` with `output_schema` | **reuse as engine, re-drive** |
| 11 | HITL A2A `input-required` pause | **`LongRunningFunctionTool`** (ask-the-human) **or** a custom-agent checkpoint to session state (recommended — see §4) | **replace** |
| 12 | `common/memory/*` (GCS bank + `pg/*` recall, CQRS) | keep verbatim; expose reads as `FunctionTool`s; optionally a thin `BaseMemoryService` adapter for `load_memory` ergonomics | **reuse** |
| 13 | `common/learn/*` lesson loop + head-of-request `drain` | keep verbatim; the head-of-request drain + pgvector projection become an **ADK Plugin** (`before_run_callback`) | **reuse, re-host trigger** |
| 14 | `common/atlassian/*`, `common/codegraph/*`, `common/extract/*` | `FunctionTool`s (crawl fetchers, codegraph build, ADF/HTML extract) | **reuse** |
| 15 | KGA crawl engine (`loop/*`, `explore/*`) | a **custom `BaseAgent`** (`GatherAgent`) whose `_run_async_impl` calls the existing `crawl()`/`expansion_round()` and yields progress events | **reuse behind BaseAgent** |
| 16 | TPD implement engine (`implement/*`, `render/*`) | a **custom `BaseAgent`** (`ImplementAgent`) wrapping `implement_plan()`; scenarios stay an `LlmAgent` call | **reuse behind BaseAgent** |
| 17 | `test_evaluation/*` metrics + golden | ADK **custom metrics** + **evalsets**; `adk eval` harness | **rebuild on ADK eval — Plan B** |
| 18 | Cloud Run sidecar (bridge :8080 + agent :8081), Cloud SQL, GCS, secrets, `/livez` | **unchanged**; only the agent container's start command changes (`to_a2a` app instead of `server:app`) | **reuse** |

**Reuse-vs-replace ledger (one line):** *replace* the `a2a-sdk` shell (rows 1–5, 11) and *rebuild*
the evaluator (17); *reuse unchanged* the entire neutral engine (6, 8, 12–16, 18) and *wrap* the
model + interrogation drive (9, 10). ~70% of LOC is reuse.

---

## 3. Determinism — the central design decision

The pipeline is deterministic today and the team fought to keep it that way (the B-gates, the single-
LLM-call implement). **ADK does not force an LLM-driven loop.** Its *workflow agents*
(`SequentialAgent`/`LoopAgent`/`ParallelAgent`) and *custom `BaseAgent`* provide **deterministic
orchestration** — the model is invoked only where we choose. So the transfer is:

> **Re-express the Python control flow as an ADK workflow-agent graph; keep every LLM call a leaf
> `LlmAgent` (or an internal one-shot `complete()`), exactly as today.**

Concretely:
- A fixed sequence of steps → `SequentialAgent([...])`.
- A bounded repeat-until-converged (the explore loop, the round advance) → `LoopAgent(max_iterations=…)`
  with a sub-agent that `escalate`s on the stop condition (converged / budget / drift).
- A chunk of imperative Python that must run as-is (BFS crawl, coverage-matrix heuristics, Gherkin
  render) → a custom `BaseAgent` that calls the existing function and `yield`s events. **This is
  encouraged** — it means the hard-won engine code is not rewritten, only re-triggered.
- A single structured-JSON LLM call (questions, scenarios) → an `LlmAgent` with `output_schema` (or
  keep the internal `complete()` call inside a tool, if the JSON-repair/fallback logic is intricate).

What we deliberately **do not** do: turn gather/refine/define into an autonomous "LLM decides the
next tool" agent. That would discard B0–B6 and the determinism. (If the team ever wants that, it is
the *separate* "interrogator" agent the `adk-vs-current-stack` diagram sketched — out of scope here.)

---

## 4. Human-in-the-loop (the refine/define pause-resume)

Today: the agent emits questions and returns A2A `input-required`; the next turn rehydrates
`state.json` and ingests the answer. Two ADK ways to reproduce this:

**Option A — `LongRunningFunctionTool` (`ask_human`).** The interrogation agent calls a long-running
tool that returns *pending*; the runner pauses; the bridge collects the human answer and resumes the
run by supplying the tool result. This is ADK's documented HITL primitive.
> ⚠️ **Known risk [verify @1.22]:** long-running/HITL tools nested inside a `SequentialAgent` have
> reported resume bugs — sub-agents re-execute on resume, and sub-agent LRO resume can fail
> (adk-python issues #3348, #5349, #3184, #5064). Because refine/define are exactly "multi-round HITL
> inside a sequence," **this must be de-risked by a spike before bulk porting** (see roadmap A0).

**Option B — custom `BaseAgent` that checkpoints to session `state` (recommended).** Keep today's
proven shape: the interrogation agent writes its loop state into ADK **session state** (not a GCS
`state.json`), emits the question round as its response, and **ends the invocation**. The next A2A
turn is a fresh invocation that reads the state back and advances — identical to today, but the
"state.json + resolve_session" plumbing is replaced by ADK's `SessionService`. This sidesteps the
LRO-in-Sequential bugs entirely and is the smaller conceptual leap. **Plan A defaults to Option B**,
with Option A kept as a fast-follow once the spike clears it.

Either way, **`context_id` → ADK `session_id`**, and the interrogation loop state
(pending rounds, deferred/carried Qs, answered set, insight ids, pass counter) moves from
`memory/{refine,test-plan}/<ctx>/state.json` **into ADK session `state`**.

---

## 5. State, memory, artifacts — three ADK services, mapped precisely

| Concern today | ADK service | Notes |
|---------------|-------------|-------|
| A2A `Task` lifecycle (`DatabaseTaskStore`, Cloud SQL) **+** interrogation `state.json` (GCS) **+** `_sessions/*.json` a2a→pack map | **`DatabaseSessionService`** on the `common/db.py` engine | **Collapses 3 mechanisms into 1.** `session_id = context_id`; loop state → `state`; the a2a→pack mapping disappears (one id). |
| GCS markdown memory bank — the record/event-log + link-graph index (CAS) + notes/insights | **keep as-is** (custom store); expose reads (`search_memory`, `get_note`) as `FunctionTool`s | ADK's `MemoryService` is thinner than this CQRS design — do **not** force-fit it. Optionally add a `BaseMemoryService` adapter so an `load_memory` tool reads the same bank. |
| pgvector recall tier (`pg/*`, hybrid vector∪tsvector∪SQL) | **keep as-is**; called by the same recall FunctionTool | Backend flag `MEMORY_BACKEND=gcs\|hybrid` unchanged. |
| rendered human artifacts (`scenarios.md`, `.feature`, `plan-brief.md`) | optionally also register with **`GcsArtifactService`** (already GCS) for the `adk web` UI | The bank stays the authority; artifacts are a convenience mirror, not a second source of truth. |

**Why this is a real win, not just a port:** today's *two* durability systems (Postgres tasks + GCS
state files) and the bespoke `resolve_session` id-mapping all collapse into ADK's single session
store. Fewer moving parts, one place to reason about durability, and the `adk web` timeline shows the
full event log for free.

---

## 6. Callbacks / Plugins — where the cross-cutting logic goes

Today every executor does the same head-of-request work: `learn.drain(bank)` (flush pending lesson
captures, off-path) + `maybe_drain_index(bank)` (pgvector projection) + route. Under ADK:

- **Head-of-request drain + projection → an ADK `Plugin`** (`before_run_callback`), registered once
  on the Runner, so it runs for **every** agent/skill without per-handler wiring. Cleaner than the
  copy-pasted preamble in each executor.
- **Lesson recall injection (B4/B5) → `before_model_callback`** (or a `load_memory`-style tool):
  inject the grounded, `scope='shared'` recalled lessons into the LlmAgent's request under the same
  "don't re-learn these" heading.
- **Lesson capture (L3/L5) → `after_agent_callback`**: enqueue the async `CaptureJob` at step end.
- **The B-gates stay where they are** (pack loader, `graph_index`, `pg/store`) — callbacks only move
  the *triggers*, not the gate logic.

## 7. Claude via LiteLlm — the hop and its gotchas

`LlmAgent(model=LiteLlm(model="vertex_ai/claude-sonnet-5", ...))`. Carry these forward or they will
regress silently:

- **Thinking must stay disabled.** Today `complete()` sets `thinking={"type":"disabled"}` so all of
  `max_tokens` goes to output; tight-budget JSON (questions ≤6000, brief 700, distill 200) truncates
  otherwise. Under LiteLlm this moves to model kwargs / `generate_content_config`. **Validate that a
  disabled-thinking request actually reaches Vertex** — this is the #1 silent-regression risk.
- **First-text extraction is handled by ADK** (content parts), replacing the manual `first_text()`
  that skipped the leading `ThinkingBlock`.
- **max_tokens tuning** (the 1500→6000 fix that stopped mid-array JSON truncation) must be set per
  LlmAgent / per call.
- **Blocking → async**: LlmAgent model calls are async under ADK, so the manual `asyncio.to_thread`
  around `complete()` for *LLM* calls goes away. But **CPU/blocking engine work** (BFS crawl,
  codegraph build, heuristic generation) inside a custom `BaseAgent` must **still** be offloaded with
  `asyncio.to_thread`, or Cloud Run's `/livez` probe starves (the `ERROR_TIMEOUT` incident). The
  liveness/timeout config on Cloud Run is unchanged.
- **Structured output**: prefer `LlmAgent(output_schema=…)` over hand-parsing where the JSON contract
  is simple; keep the tolerant `loads_array` + heuristic fallback for the intricate cases (it already
  guards against LLMs returning a scalar field as a list).

## 8. What the MCP client (Claude Code) sees — nothing changes

The bridge and its MCP tool names/signatures (`gather_knowledge`, `refine`, `define_plan`,
`implement_plan`, `evaluate_pack`, …) are **unchanged**. The bridge still speaks MCP→A2A; the agent
behind it is still an A2A endpoint (now produced by `to_a2a`). This keeps the transfer invisible to
users and lets it ship agent-by-agent behind the same URLs.
