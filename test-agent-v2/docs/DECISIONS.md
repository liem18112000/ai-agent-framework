# Decision record — v2 ADK build (E8)

Load-bearing decisions where **v2 deliberately diverges from the canonical `adk-samples` idioms**, or
where an implementation choice is easy to mistake for an oversight. Read this before "fixing" any of
them. Each entry: *Decision · Why · Consequence · Status*. Invariants (I1–I7) are defined in
[`IMPLEMENTATION-PLAN.md`](IMPLEMENTATION-PLAN.md) §1; the sample idioms in
[`ENHANCEMENT-adk-idioms.md`](ENHANCEMENT-adk-idioms.md).

---

## D1 — Keep custom `BaseAgent` routers + engine wrappers + the HITL loop
- **Decision:** the KGA/TPD roots are custom `BaseAgent` text-dispatch routers; gather/implement wrap
  the reused engines in `BaseAgent`s; refine/define are a `BaseAgent` HITL loop. The samples use
  **zero** custom `BaseAgent` (they compose `SequentialAgent`/`LlmAgent`+`AgentTool`).
- **Why:** the MCP bridge speaks a **deterministic text-command protocol** (`gather`/`refine`/…), the
  pipeline is deterministic (B0–B6, one-LLM-call implement — I1), the engines are large imperative
  Python re-triggered not rewritten, and refine/define need **pause/resume across A2A turns** (proven
  in the A0 spike). ADK explicitly reserves custom `BaseAgent` for exactly this bespoke control flow.
- **Consequence:** more `BaseAgent` code than a Gemini chat agent, but determinism + the reused engine
  are preserved. **Do not** convert the routers to an `LlmAgent`+`AgentTool` coordinator on the default
  path — that makes dispatch LLM-driven (breaks I1), adds an LLM call/latency to every step, and breaks
  the bridge's text contract.
- **Status:** permanent.

## D2 — Orchestration is client-driven + gated, not in-agent
- **Decision:** the pipeline (gather→refine→approve→define→approve→implement) is orchestrated by the
  **client** (Claude Code), one A2A call per step, with a human confirm-gate before each. There is no
  in-agent coordinator on the default path.
- **Why:** the confirm-gates + human-in-the-loop are a **product requirement**, not a limitation. Each
  A2A call is therefore a single deterministic step — which is why the samples' "coordinator LlmAgent
  calls specialists" pattern doesn't map onto the default path.
- **Consequence:** per-call agents are single-purpose. Autonomy is available *opt-in* (see D3).
- **Status:** permanent for the gated path.

## D3 — The autonomous pipeline is a `SequentialAgent`, not an `LlmAgent`+`AgentTool` coordinator (E7)
- **Decision:** `testing_agent.root_agent = SequentialAgent([gather, refine, define, approve,
  implement])`. The original enhancement plan proposed an `LlmAgent`+`AgentTool` coordinator.
- **Why:** the step order is **fixed**, so the canonical + deterministic choice is a workflow agent
  (the `llm-auditor` idiom) — no LLM router needed, determinism preserved (I1). An LLM coordinator would
  only be warranted if it had to *decide* the order/steps, which it doesn't.
- **Consequence:** the headless sub-agents (`RefineAgent`/`DefineAgent`/`ApproveAgent`, one class per
  module under `testing_agent/subagents/`) wrap the reused `refine`/`define` drivers with
  `accept_recommendation`. Opt-in; the gated path is untouched. (`SequentialAgent` now emits a
  deprecation warning toward `Workflow`; migration is deferred — see D10.)
- **Status:** adopted (supersedes the plan's E7 sketch).

## D4 — Cross-cutting logic lives in a Runner `Plugin` (`before_run`), not per-agent callbacks (E4)
- **Decision:** `LearnDrainPlugin`/`LessonRecallPlugin` are Runner **Plugins** (`before_run_callback`),
  not per-agent `before_model`/`before_tool` callbacks.
- **Why:** v2's LLM calls happen **inside the reused engine**, not via ADK `LlmAgent`s, and its I/O is
  direct, not via ADK `tools=[...]`. So ADK's `before_model`/`before_tool` callbacks **have no attach
  point** — there's no ADK-mediated model/tool call to wrap. A Runner Plugin's `before_run` fires per
  invocation for every agent regardless.
- **Consequence:** `LessonRecallPlugin` is inert until/unless QuestionGen/etc. become real `LlmAgent`s;
  grounded recall runs in the engine (`_recall_into`) on the gated path today.
- **Status:** current; revisit only if agents are converted to `LlmAgent`s.

## D5 — Model = Claude via LiteLlm (swappable), not Gemini-native
- **Decision:** `agent_model()` returns `LiteLlm("vertex_ai/claude-sonnet-5")` by default; Gemini is a
  one-env-var switch (`TESTAGENT_MODEL_BACKEND`, E2). The samples are Gemini-first.
- **Why:** explicit user decision — preserve today's Claude Sonnet 5 behavior; the LiteLlm hop is the
  known cost.
- **Consequence:** the thinking-disabled + max_tokens gotchas must survive the LiteLlm hop (I5).
- **Status:** default, but configurable.

## D6 — Reuse the v1 engine (~70%) unchanged
- **Decision:** `common/{memory,learn,interrogate,llm,atlassian,codegraph,extract}` and the agents'
  engine subpackages are copied from v1 and reused; only the a2a-sdk shell is replaced.
- **Why:** the whole point of the migration is to re-host, not rewrite. Determinism + B0–B6 live in
  that engine.
- **Consequence:** `test-agent-v1` is the upstream during transition; engine fixes are cherry-picked.
- **Status:** permanent (until the engine is promoted to a shared installable package — a follow-up).

## D7 — Interrogation state reuses each session's bank persistence, not ADK session state
- **Decision:** `InterrogationAgent` drives `RefineSession`/`PlanSession`, which persist to (and
  rehydrate from) the **GCS bank** keyed by the context id (= the ADK `session_id`, held constant by
  the bridge). It does **not** re-port the loop state into ADK session `state`.
- **Why:** the bank persistence is already tested and carries insights/decisions/questions + B0–B6;
  re-implementing it in ADK state is risk for no gain. (The A0 spike proved the pause/resume *mechanic*;
  the real engine reuses its own store.)
- **Consequence:** ADK session state carries only a small activity marker. The "collapse two durability
  systems into one `DatabaseSessionService`" benefit is realized for the A2A task lifecycle, not the
  interrogation store.
- **Status:** current.

## D8 — Cloud Run + MCP bridge is the only deploy path; Agent Engine dropped (supersedes E6)
- **Decision:** removed the Vertex Agent Engine path (`deployment/deploy.py` deleted). The Cloud Run
  `to_a2a` + MCP bridge is the single runtime; `deployments/test-agent-v2/install-mcp.{sh,cmd}` registers
  the three bridges with Claude Code (deployed `/mcp` URLs resolved from `terraform output`).
- **Why:** ADK has **no native "expose an agent as an MCP server"** — its MCP support is `McpToolset`, a
  *consumer* of external MCP tools — so the A2A→MCP bridge IS Claude Code's native channel to the agents.
  Agent Engine changes the client contract and drops that bridge, the whole gated Testing-Agent UX (I4/D2).
  One well-supported native path beats two half-supported ones.
- **Consequence:** `deployment/deploy.py` and the Agent Engine option are gone; DEPLOY.md now lists three
  paths. `adk deploy agent_engine` still exists natively but is intentionally unused here.
- **Status:** current (supersedes the earlier "additional target" stance).

## D8b — v2 provisions its OWN Cloud SQL Postgres (`deploy_cloudsql` default ON)
- **Decision:** flipped `deploy_cloudsql` to default `true`; the v2 stack stands up a dedicated Cloud SQL
  Postgres instance and wires `DatabaseSessionService` (DB_* env → `common/db.get_engine`).
- **Why:** durable sessions/tasks for v2 without sharing v1's DB — isolation over the extra instance cost.
- **Consequence:** two Cloud SQL instances (v1 + v2). The DB password is terraform-generated
  (`random_password` → Secret Manager), no secret to supply. `deploy_cloudsql=false` reverts to in-memory
  sessions (the GCS memory bank stays durable regardless).
- **Status:** current.

## D9 — Freed the canonical `agent.py` name via an `a2a_card.py` rename, not by dropping v1 (E1)
- **Decision:** each agent's v1 A2A card moved to `a2a_card.py`; the ADK root took `agent.py` (so
  `adk web`/`adk run` discover `root_agent`), while the v1 shells + tests keep working.
- **Why:** a non-destructive way to get canonical discovery *now* without dropping the still-load-bearing
  v1 shells.
- **Consequence:** a `a2a_card.py` module per agent during the transition; retire it when the v1 shells
  are dropped at the deploy milestone.
- **Status:** transitional.

---

## D10–D13 — the ADK-native cutover (see [`ENHANCEMENT-adk-native-cutover.md`](ENHANCEMENT-adk-native-cutover.md))

Recorded from the cutover enhancement (drop the a2a-sdk shells + Gemini + the dual model plumbing).
Full rationale/milestones/gates live in that doc; the one-liners here keep the record coherent.

## D10 — Model access via a `ModelProvider` interface; Gemini removed
- **Decision:** model access goes through a small `common/adk/providers` interface;
  `VertexClaudeProvider` is the **sole** concrete impl; the `gemini` backend + `gemini_model` are deleted.
- **Why:** user decision — *abstract* Claude-on-Vertex behind an extension point, don't carry a second
  backend. A future `LocalClaudeProvider` (e.g. `ANTHROPIC_BASE_URL`) becomes a one-line registry entry.
- **Consequence:** the I5 thinking/max_tokens gotchas live in the provider (one place); the engine keeps
  its own `common/llm/vertex.py` transport (Option A) — routing the engine through the provider is a
  tracked follow-up (Option B). New invariant **I8** (model only via the provider).
- **Status:** planned (supersedes **D5**'s "one-env-var Gemini switch").

## D11 — One ADK-native entrypoint (`main:app`) + one MCP gateway
- **Decision:** `main.py` (`get_fast_api_app`, `a2a=True`) is the single server; `src/gateway` is local
  Claude's single MCP entry. Per-agent `adk_app.py` (`to_a2a`), `server.py`, `a2a_card.py`, and the
  standalone per-agent bridge launchers are dropped; each agent's `bridge/mcp_server.register_tools`
  (the MCP surface, I4) is kept and composed by the gateway.
- **Why:** "collapse to ADK-native" — one well-supported native surface over three overlapping ones.
- **Consequence:** the gateway, the **A2A-only agents**, and the deletion of the standalone per-agent
  bridge launchers **already landed in the G-milestones** (see [`DESIGN-mcp-gateway.md`](DESIGN-mcp-gateway.md));
  the remaining delta here is collapsing each per-agent `adk_app.py` (`to_a2a`) into `main:app` (C4).
  Rollback = restore the Dockerfile CMD to `<agent>.adk_app:app`.
- **Refined as-built (C4):** `main:app` = **`to_a2a(single agent selected by $AGENT)`, root-mounted at
  `/`** — NOT `get_fast_api_app`/`/a2a/<app>/`/`/list-apps`. The gateway topology runs three *separate*
  agent Cloud Run services, so each container serves exactly one agent; `services.tf` sets `AGENT` per
  service. See §12 of the enhancement doc.
- **Status:** **DONE (C4).** Extends/supersedes **D8**.

## D12 — Domain logic extracted from `executor/`; the a2a `*Executor` shells dropped
- **Decision:** the framework-neutral functions trapped in each `executor/` package (`run_gather`,
  `wants_refine`, `summarize_define`, `run_implement`, `golden_for`, …) move to neutral modules; the
  `*Executor` classes + the a2a `reply`/`now` seam are deleted.
- **Why:** the ADK agents already reuse those functions; extraction is the precondition for deleting the
  shells without regressing the equivalence suite.
- **Consequence:** completes the **D6/D9** transition; `build_bank` importers repoint to
  `common/memory/factory.py`; `now()` moves to `common/adk/util.py`.
- **Status:** **DONE (C2 + C3).** Neutral modules landed in C2; the `executor/` packages deleted in C3.

## D13 — Bearer auth is transport-neutral middleware on `main:app`; sessions subsume the task store
- **Decision:** `BearerAuthMiddleware` is relocated (not deleted) to `common/adk/auth.py` and wraps
  `main:app`; `DatabaseSessionService` (`SESSION_SERVICE_URI`) is the one durable store, retiring the
  a2a `DatabaseTaskStore`.
- **Why:** `get_fast_api_app` ships no auth and no separate task store — deleting the middleware outright
  would leave the A2A surface open.
- **Consequence:** verify `DatabaseSessionService` persists the A2A task lifecycle
  (`[verify @2.x]`, R-c in the enhancement doc).
- **Status:** **DONE (C3 + C4).** `common/adk/auth.py` in place, wrapped on `main:app` (`build_runner`
  builds the DatabaseSessionService-backed Runner); live task-lifecycle persistence stays R-c/`[verify @2.x]`.

## D14 — A2A cards left to ADK's auto-generation; hand-authored cards + `common/card.py` dropped
- **Decision (revised):** delete the three `src/<pkg>/a2a_card.py` **and** `common/card.py`; `main.build_app`
  calls `to_a2a(root, runner=…)` with **no** `agent_card=`, so ADK generates the A2A card. *(This reverses
  the interim "keep the rich card via `agent_card=`" call after review — user chose the leaner, fully
  ADK-native surface.)*
- **Why:** the hand-authored cards + `common/card.py` + the dynamic `_agent_card()` seam in `main.py` were
  ~4 files kept only to prettify an *internal* A2A surface. The rich, client-facing layer is the **MCP
  gateway's** tool descriptions (I4), which are unchanged; the A2A card is agent-to-agent + the gateway's
  `agent_cards` diagnostic, where ADK's generic card (`name="knowledge_gathering"`, `"An ADK Agent"`, auto
  skill ids) is acceptable. `to_a2a`'s `agent_card=` override still exists if a real card is wanted later.
- **Consequence:** `common/card.py` deleted (its only importers were the a2a_card files); `main.py` drops
  `_agent_card()`; `test_main` asserts the ADK card (`name="knowledge_gathering"`, skills non-empty).
- **Status:** **DONE (C4).**

## D15 — KGA explore leaf LLM steps are ADK `LlmAgent(output_schema=…)`, driven by `GatherAgent`, via the provider
- **Decision:** `hypothesize` + `ask_llm` (leads) become ADK `LlmAgent`s with a pydantic `output_schema`;
  `GatherAgent` runs them under its `ctx` behind `KGA_LLM_HYPOTHESIZE`/`KGA_LLM_LEADS` (default OFF) and
  feeds `terms=`/`leads=` into the unchanged deterministic `expansion_round`+`crawl`. Model via
  `agent_model()` — the provider's first live `LlmAgent` consumer (I8). Raw `complete()`+`_coerce_*` deleted.
- **Why/consequence:** realizes D10 "Option B" for the explore steps; deletes hand-rolled JSON coercion;
  keeps I1 (flags off → zero LLM calls, identical nodes). `output_schema` ⇒ no tools/transfer (fine, pure
  enumerators).
- **Status:** **DONE (P0–P3, P5).** P4 (ctx-less loop shim) deferred — the loop is inert under the ADK
  GatherAgent (A1). See [`ENHANCEMENT-explore-llmagent.md`](ENHANCEMENT-explore-llmagent.md).

## D16 — TPD implement generators are ADK `LlmAgent(output_schema=…)`, leaf-first, via the provider, preserving I3
- **Decision:** the implement generators (`scenarios` flagship + detail-gated `test_data`/`steps`) become
  ADK `LlmAgent`s with pydantic `output_schema`, driven by `ImplementAgent`; `implement_plan` is async
  (no `to_thread`). Model via `agent_model()` (I8); `complete()`+`loads_array` deleted from the implement
  `llm/*`. Heuristic fallback on invalid output preserved.
- **Why/consequence:** reuses ADK's agent machinery, deletes hand-parsers; **I3 preserved** — default
  implement = exactly 1 LLM call (scenarios), `test_data`/`steps` stay behind `detail`/`TPD_LLM_DETAIL`
  (locked by call-count tests: default=1, detail=3).
- **Status:** **DONE (T0–T5).** T6 (QuestionGen/brief via the shared `common/adk/interrogation.py`, KGA
  refine rides on it) deferred as a coordinated follow-up. See [`ENHANCEMENT-tpd-llmagent.md`](ENHANCEMENT-tpd-llmagent.md).

## D17 — TEV's judged tier runs through the provider + ADK-native judged metrics; the live scorer stays deterministic
- **Decision:** add a provider-sourced judge/embeddings factory (`eval/judge.py`, from `agent_model()`);
  route RAGAS through it (no silent OpenAI default — `ragas_judge.judge` raises on `None`); wire the
  defined-but-unwired `judge_semantic` as an opt-in judged rubric; wire ADK-native `JUDGED_METRICS` into
  `eval/config.py`+`runner.py`, creds-gated. The live `evaluate_pack`/`evaluate_plan` A2A path stays
  **deterministic + LLM-free** (asserted by a zero-LLM-call test).
- **Why/consequence:** the only genuine "reuse ADK more" for an evaluator is a provider-sourced judge (I8)
  + ADK's native judged harness — NOT agent-ifying deterministic scoring (that would destroy PQS/TPS
  reproducibility). Realizes the "Open: judged eval tier" item.
- **Status:** **DONE (V0–V4).** Live RAGAS tier needs `langchain-community`/`langchain-google-vertexai`
  in the `eval` extra (never imported offline; follow-up). See [`ENHANCEMENT-tev-adk-reuse.md`](ENHANCEMENT-tev-adk-reuse.md).

---

## Open (not yet decided / deferred to the deploy milestone)
- **Stable `context_id → session_id` mapping** across the gather→refine→… A2A calls when serving via
  `to_a2a` (the bridge must pass a stable ADK `session_id`, or `to_a2a` must derive it from the A2A
  `context_id`). Verified in tests with a fixed `session_id`; the production wiring is A1-d/A2-d.
- **Live `DatabaseSessionService`** (currently InMemory offline; DB path wired but unexercised).
- **Dropping the v1 shells** (server.py / executors / `a2a_card.py`) once v2 is deployed — unblocks the
  final cleanup.
- **Judged eval tier** (`hallucinations_v1` / `rubric_based_*`) with a judge model.

<!-- The single-MCP-gateway decision (built in the G-milestones: gateway + A2A-only agents, standalone
per-agent bridges deleted) is recorded under D11 below and in DESIGN-mcp-gateway.md — it is NOT a
separate D10 (that number is the ModelProvider decision above). -->

