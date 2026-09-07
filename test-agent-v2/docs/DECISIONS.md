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
- **Decision:** `testing_agent.root_agent = SequentialAgent([gather, refine_auto, define_auto,
  approve_auto, implement])`. The original enhancement plan proposed an `LlmAgent`+`AgentTool` coordinator.
- **Why:** the step order is **fixed**, so the canonical + deterministic choice is a workflow agent
  (the `llm-auditor` idiom) — no LLM router needed, determinism preserved (I1). An LLM coordinator would
  only be warranted if it had to *decide* the order/steps, which it doesn't.
- **Consequence:** the headless auto-agents wrap the reused `refine`/`define` drivers with
  `accept_recommendation`. Opt-in; the gated path is untouched.
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

## D8 — Agent Engine is an additional deploy target, not a replacement for Cloud Run (E6)
- **Decision:** `deployment/deploy.py` deploys to Vertex **Agent Engine** (default target
  `testing_agent`); the Cloud Run `to_a2a` + MCP bridge stays the primary runtime.
- **Why:** Agent Engine changes the client contract (no A2A/MCP bridge), so it suits the autonomous
  consumer; the gated KGA/TPD depend on the bridge (I4).
- **Consequence:** two deploy paths; choose per environment/consumer.
- **Status:** optional.

## D9 — Freed the canonical `agent.py` name via an `a2a_card.py` rename, not by dropping v1 (E1)
- **Decision:** each agent's v1 A2A card moved to `a2a_card.py`; the ADK root took `agent.py` (so
  `adk web`/`adk run` discover `root_agent`), while the v1 shells + tests keep working.
- **Why:** a non-destructive way to get canonical discovery *now* without dropping the still-load-bearing
  v1 shells.
- **Consequence:** a `a2a_card.py` module per agent during the transition; retire it when the v1 shells
  are dropped at the deploy milestone.
- **Status:** transitional.

---

## Open (not yet decided / deferred to the deploy milestone)
- **Stable `context_id → session_id` mapping** across the gather→refine→… A2A calls when serving via
  `to_a2a` (the bridge must pass a stable ADK `session_id`, or `to_a2a` must derive it from the A2A
  `context_id`). Verified in tests with a fixed `session_id`; the production wiring is A1-d/A2-d.
- **Live `DatabaseSessionService`** (currently InMemory offline; DB path wired but unexercised).
- **Dropping the v1 shells** (server.py / executors / `a2a_card.py`) once v2 is deployed — unblocks the
  final cleanup.
- **Judged eval tier** (`hallucinations_v1` / `rubric_based_*`) with a judge model.
