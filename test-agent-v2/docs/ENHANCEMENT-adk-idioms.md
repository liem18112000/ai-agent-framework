# Enhancement plan — align v2 with the canonical ADK-samples idioms

A proposed enhancement layer for `test-agent-v2/`, grounded in the official
[`google/adk-samples`](https://github.com/google/adk-samples) `contrib/python/` agents (read in full:
`llm-auditor`, `financial-advisor`, `market-research-agent`, and `python/agents/customer-service`).
The goal is to adopt the sample idioms **where they add real value**, and to **consciously diverge —
with documented rationale — where v2's constraints differ**. This is a design proposal (docs only);
each milestone below is independently executable.

> Reading order: this builds on [`IMPLEMENTATION-PLAN.md`](IMPLEMENTATION-PLAN.md) (M0→B, all offline
> gates green) and the design in [`../../docs/adk-transform/`](../../docs/adk-transform/).

> **Progress (2026-09-08):** ✅ **E3, E2, E5, E7, E1, E4 DONE** (offline). **398 passed, 14 skipped,
> ruff clean.**
> - **E3** — `common/adk/tools.py` bare typed functions (Google docstrings; `memory_tools()` returns
>   callables ADK auto-wraps).
> - **E2** — `common/adk/config.py` (pydantic-settings `Config`; `agent_model()` switches
>   Claude-via-LiteLlm ↔ Gemini via `TESTAGENT_MODEL_BACKEND`) + `.env.example` + `pydantic-settings` dep.
> - **E5** — `test_evaluation/eval/{evalset.write_eval_data,runner.run_agent_eval}` emit canonical
>   `data/*.evalset.json` + `test_config.json` (committed) + the creds-gated `AgentEvaluator` harness.
> - **E7** — `src/testing_agent/` (a THIRD package composing KGA + TPD): `agent.py` exports
>   `root_agent = SequentialAgent([gather, refine_auto, define_auto, approve_auto, implement])` — the
>   opt-in autonomous "test LUZ-xxx" one-shot. **Refined the plan: since the order is fixed, this is a
>   `SequentialAgent` (llm-auditor idiom), NOT an `LlmAgent`+`AgentTool` coordinator** — no LLM router,
>   determinism preserved (I1). The headless auto-agents wrap the reused `refine`/`define` drivers with
>   `accept_recommendation`. Verified end-to-end offline (`tests/test_adk_autonomous.py`).
> - **E1 (FULL)** — done the `agent.py` rename without dropping the v1 shell: each agent's v1 A2A card
>   moved to **`a2a_card.py`** and the ADK root promoted to the canonical **`agent.py:root_agent`**; the
>   evaluator got a new `agent.py` (`EvaluatorAgent`). `__init__.py` bootstrap (`load_dotenv` +
>   `GOOGLE_GENAI_USE_VERTEXAI` + best-effort `google.auth.default()` + `from . import agent`);
>   `python-dotenv` dep; `.env.example`. **Gate met:** ADK's own `AgentLoader(agents_dir="src")` (what
>   `adk web`/`adk run` use) discovers all four — `knowledge_gathering`, `test_plan_definition`,
>   `test_evaluation`, `testing_agent`. All import sites redirected; 398 pass, ruff clean.
> - **E4** — verified the cross-cutting `LearnDrainPlugin.before_run_callback` fires + drains. **Finding:
>   v2's LLM calls happen inside the reused engine (not via ADK `LlmAgent`s), so ADK's per-agent
>   `before_model`/`before_tool` callbacks have no attach point — cross-cutting logic correctly lives in
>   a Runner `Plugin` (`before_run`). Per-agent model callbacks become relevant only if QuestionGen/etc.
>   are ever converted to real `LlmAgent`s.** `LessonRecallPlugin` stays inert until then; grounded
>   recall runs in the engine (`_recall_into`) on the gated path.
>
> - **E6** — `deployment/deploy.py`: deploys a v2 ADK agent to Vertex **Agent Engine**
>   (`AdkApp(enable_tracing=True)` + `agent_engines.create(requirements=[pinned], extra_packages=["./src"])`,
>   `--create/--delete/--list`, default target `testing_agent`). `vertexai` imported lazily so it parses
>   offline; `tests/test_adk_deploy.py` verifies the CLI + agent resolution. An **additional** target —
>   Cloud Run `to_a2a` + the MCP bridge stay primary.
> - **E8** — [`DECISIONS.md`](DECISIONS.md): the decision record (D1–D9 + open items) for the conscious
>   divergences, so they aren't "fixed" by mistake.
>
> ✅ **All E1–E8 done.** **400 passed, 14 skipped, ruff clean.** Remaining is the deploy milestone
> (outside the E-series): live `DatabaseSessionService`, the stable `context_id → session_id` mapping,
> and retiring the v1 shells (`server.py`/executors/`a2a_card.py`).

---

## 1. The canonical baseline (what the samples do)

Verified from the sample source:

- **Structure:** each agent is a package with **`agent.py` that assigns a module-level `root_agent`**
  variable — the hard contract the `adk web`/`adk run`/`adk eval` CLIs discover. `__init__.py`
  bootstraps env/auth (`load_dotenv()` → `google.auth.default()` → set `GOOGLE_GENAI_USE_VERTEXAI`)
  **before** importing `agent`. Sub-agents in `sub_agents/<name>/agent.py`. Prompts in a `prompt.py`
  of UPPER_SNAKE constants. Top-level `eval/`, `deployment/`, `tests/`, `.env.example`, `pyproject.toml`.
- **Three orchestration shapes — and no custom `BaseAgent` anywhere:**
  1. **Fixed pipeline → `SequentialAgent(sub_agents=[...])`** (llm-auditor: `critic → reviser`).
  2. **Dynamic multi-specialist → one `LlmAgent` with `tools=[AgentTool(agent=child), …]`** and
     inter-agent state via `output_key` + prompt references (financial-advisor, market-research). Even
     "parallel" is done by *prompting* the coordinator to emit all tool calls at once — not `ParallelAgent`.
  3. **Single `LlmAgent` + many function tools** (customer-service), with all custom logic in **callbacks**.
- **Tools = plain typed functions** passed bare in `tools=[...]` (ADK auto-builds the schema from
  type hints + Google-style docstrings); they return `dict`/JSON and **do not** take `ToolContext`.
  State/guardrails live in **callbacks**, not tools.
- **Callbacks carry the custom logic:** `before_agent` (seed session state), `before_model`
  (rate-limit; patch empty `LlmRequest` parts — a real gotcha), `before_tool` (**return a dict to
  short-circuit** a tool = a deterministic guardrail), `after_tool`/`after_model` (post-process).
- **Config:** env-only (`os.getenv("MODEL_NAME")` + `.env`) or a **pydantic-settings `Config`** class
  (customer-service). `.env.example` ships `GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_CLOUD_PROJECT/LOCATION`.
- **Eval:** `eval/test_eval.py` calls `AgentEvaluator.evaluate("<agent>", data_dir, num_runs=…)` under
  pytest; `eval/data/*.test.json` (or `*.evalset.json`) + `test_config.json`
  (`{"criteria": {"tool_trajectory_avg_score": 1.0, "response_match_score": 0.35}}`).
- **Deployment:** `deployment/deploy.py` wraps `AdkApp(agent=root_agent, enable_tracing=True)` and
  calls `vertexai … agent_engines.create(…, requirements=[pinned], extra_packages=["./<pkg>"], env_vars=…)`
  — **Vertex Agent Engine**. `to_a2a`/Cloud Run is *not* in these samples.
- **Imports/pins:** `from google.adk import Agent` (== `LlmAgent`), `from google.adk.agents import
  SequentialAgent`, `from google.adk.tools.agent_tool import AgentTool`; `google-adk>=1.31` (newest
  sample), companions `google-cloud-aiplatform[adk,agent_engines]`, `google-genai`, `pydantic`,
  `python-dotenv`. No `Runner` appears — samples rely on `adk web`/`AgentEvaluator`/`AdkApp`.

---

## 2. Gap analysis — v2 vs. canonical

| # | Idiom | Canonical | v2 today | Verdict |
|---|-------|-----------|----------|---------|
| G1 | `root_agent` in **`agent.py`**; `__init__` env bootstrap | yes (CLI-discoverable) | `root_agent` in `adk_agent.py` (v1's `agent.py` holds the A2A card) | **Adopt** once v1 shell drops |
| G2 | Deterministic flow = `SequentialAgent`/workflow | yes | custom `BaseAgent` routers + engine wrappers | **Keep — documented divergence** (bespoke control flow; ADK sanctions BaseAgent for it) |
| G3 | Dynamic orchestration = `LlmAgent` + `AgentTool` | yes | client-driven gated steps (no in-agent orchestration) | **Adopt-adapted** — add an *optional* autonomous coordinator; keep the gated path |
| G4 | Sub-agents in `sub_agents/<name>/agent.py` | yes | `agents/<name>.py` | **Adopt** (cosmetic re-layout) |
| G5 | Tools = plain typed functions (no `FunctionTool(...)`) | yes | `FunctionTool(func=…)` in `tools.py` | **Adopt** (simplify) |
| G6 | Custom logic in **callbacks** | per-agent callbacks | cross-cutting **Plugins** (`before_run`/`before_model`) | **Keep + extend** — Plugins are the newer cross-cutting form; add per-agent callbacks where sample-idiomatic |
| G7 | `Config` (pydantic-settings) + `.env.example` | yes | scattered `os.getenv` via `common/llm/vertex` | **Adopt** — a `common/adk/config.py` |
| G8 | Canonical `eval/` + `AgentEvaluator.evaluate` under pytest | yes | programmatic custom-metric functions (Plan B) | **Adopt** — emit real evalset + `test_config.json`; this is Plan B's follow-up |
| G9 | `deployment/deploy.py` → **Agent Engine** | yes | `to_a2a` + Cloud Run sidecar | **Adopt as an option** alongside Cloud Run |
| G10 | Model = Gemini via env | yes | Claude via **LiteLlm** | **Keep — documented divergence** (explicit user decision); make it configurable |
| G11 | `prompt.py` UPPER_SNAKE constants | yes | reuse `common/llm/prompts` | **Keep** (already centralized; expose per-agent modules only if it helps) |

**The load-bearing insight (why v2 legitimately differs):** the samples orchestrate a *multi-step*
flow **inside one agent** (a coordinator LLM calls specialists). v2's orchestration is **external and
client-driven** — Claude Code drives `gather → refine → approve → define → approve → implement` as
separate MCP calls with a human confirm-gate before each (a product requirement + the HITL design,
invariant-adjacent). So each v2 A2A call is a **single deterministic step**, and the
"coordinator-LlmAgent-plus-AgentTool-specialists" pattern doesn't map onto the gated path. That is why
v2 has command-routers (custom `BaseAgent`) instead of an `AgentTool` coordinator — and ADK explicitly
reserves custom `BaseAgent` for exactly this "bespoke control flow." The enhancement therefore adopts
the **structural / CLI / eval / deploy / tools** idioms (real modernization) and **adds** the AgentTool
coordinator as an *optional autonomous mode*, without disturbing the deterministic gated path.

---

## 3. Enhancement milestones

Each is independently shippable; none regresses the offline gates (M0→B).

### E1 — CLI-discoverable structure (`agent.py` + `root_agent` + `__init__` bootstrap)
- **Why:** unlock `adk web` / `adk run` (dev ergonomics, visual trace) and `adk eval` for all three agents.
- **Do:** when the v1 shell is dropped (deploy milestone), rename `adk_agent.py → agent.py` (keeps the
  `root_agent` export). Add each package's `__init__.py` bootstrap: `load_dotenv()`, best-effort
  `google.auth.default()`, `os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", …)`, then `from . import agent`.
  Add `.env.example`.
- **Gate:** `adk web` lists knowledge_gathering / test_plan_definition / test_evaluation and renders a trace.
- **Size:** S (blocked on dropping the v1 `agent.py` that currently owns the name).

### E2 — `common/adk/config.py` (pydantic-settings, model-backend configurable)
- **Why:** replace scattered `os.getenv`; make the Claude-via-LiteLlm ↔ Gemini choice a single switch (G10).
- **Do:** a `Config(BaseSettings)` (env_prefix, `.env`) with `model_backend` (`"claude"` default →
  `LiteLlm("vertex_ai/claude-sonnet-5")`, or `"gemini"` → a Gemini id), project/location, feature flags.
  `claude_llm()` reads it. Ship `.env.example`.
- **Gate:** `MODEL_BACKEND=gemini` swaps the model with no code change; default unchanged.
- **Size:** S.

### E3 — Tools as plain typed functions (drop `FunctionTool(...)`)
- **Why:** match the canonical auto-schema idiom; less boilerplate (G5).
- **Do:** in `common/adk/tools.py`, pass the bare functions in `tools=[…]` (ADK wraps them); ensure
  Google-style docstrings + full type hints; return `dict`/JSON. Keep the router's *inline* command
  handlers as-is (they're not LLM tools).
- **Gate:** the memory-read tools still resolve; skill-parity + read tests green.
- **Size:** S.

### E4 — Callback alignment (keep Plugins, add the idiomatic per-agent hooks)
- **Why:** the samples encode real gotchas as callbacks (G6).
- **Do:** keep `LearnDrainPlugin`/`LessonRecallPlugin` (cross-cutting, newer form). Add, where it
  applies: a `before_model` that **patches empty `LlmRequest` parts** (the customer-service rate-limit
  gotcha) if we hit it under LiteLlm; finish `LessonRecallPlugin`'s grounded injection (the A1
  follow-up) as a `before_model` callback. Document the Plugin↔callback mapping.
- **Gate:** no behavior change on the offline suite; recall injection unit-tested.
- **Size:** S–M.

### E5 — Canonical `eval/` (real evalset + `test_config.json` + `AgentEvaluator`)
- **Why:** the sample eval harness + `adk eval` CLI; completes Plan B's follow-ups.
- **Do:** emit `test_evaluation/eval/data/*.evalset.json` (or `*.test.json`) from the golden JSON
  (extend `evalset.py`), a `test_config.json` (`criteria`: `tool_trajectory_avg_score`,
  `response_match_score`, plus our custom `pqs_score`/`tps_score`/`hard_negative_leak` via
  `custom_function_path`), and an `eval/test_eval.py` that runs `AgentEvaluator.evaluate(...)` under
  pytest against the KGA/TPD agents over the offline fixtures. Wire the judged tier
  (`hallucinations_v1`, `rubric_based_final_response_quality_v1`) with a judge model, skipping when unset.
- **Gate:** `pytest test_evaluation/eval` + `adk eval` reproduce PQS/TPS; leak gate fails a bleed case;
  judged tier runs when a judge model is configured, skips otherwise.
- **Size:** M. (Builds directly on the Plan B code already in `test_evaluation/eval/`.)

### E6 — `deployment/deploy.py` (Agent Engine option, alongside Cloud Run)
> **⚠️ Superseded / removed** (see DECISIONS **D8**): `deployment/deploy.py` and its test were deleted.
> ADK has no native MCP-server, so the A2A→MCP bridge is Claude Code's native channel; Agent Engine drops
> that bridge. The single deploy path is Cloud Run `to_a2a` + the bridge, registered via
> `deployments/test-agent-v2/install-mcp.{sh,cmd}`. `adk deploy agent_engine` still exists natively but is
> unused here. The rest of this section is retained as the original proposal.
- **Why:** the canonical managed-runtime deploy; a lower-ops alternative to the Cloud Run sidecar (G9).
- **Do:** a `deployment/deploy.py` per agent: `AdkApp(agent=root_agent, enable_tracing=True)` +
  `agent_engines.create(requirements=[pinned], extra_packages=["./src/<pkg>"], env_vars=…)`, flags
  `--create/--delete/--list`. Keep the Cloud Run `to_a2a` path (the bridge/MCP surface depends on it) —
  Agent Engine is an *additional* target, chosen per environment.
- **Note:** Agent Engine changes the client contract (no A2A/MCP bridge) — so it suits an autonomous/
  `adk web` consumer, not the existing MCP bridge. Document the trade-off; don't replace Cloud Run.
- **Gate:** `deploy.py --create` validates against a staging project (or a dry-run/plan).
- **Size:** M.

### E7 — Optional autonomous coordinator (the `AgentTool` idiom, where it fits)
- **Why:** the one place the canonical dynamic-orchestration pattern genuinely adds value — an
  autonomous "test LUZ-xxx" one-shot for users who don't want the gated step-by-step.
- **Do:** a `TestingCoordinator = LlmAgent(model=claude_llm(), instruction=…, tools=[AgentTool(gather),
  AgentTool(refine), AgentTool(define), AgentTool(implement)])` that drives the pipeline end-to-end,
  with inter-step state via `output_key`. The wrapped sub-agents **stay deterministic** (unchanged
  BaseAgents); only the coordinator is LLM-driven, and it is **opt-in** (a separate root / a
  `COORDINATOR` mode). The gated, client-driven path is untouched.
- **Gate:** an autonomous run over a recorded fixture reaches an implemented plan; the gated path is
  unaffected; B0–B6 hold (sub-agents unchanged).
- **Size:** M. **Explicitly does not** replace the gated path (invariant I1 for the sub-agents; the
  human confirm-gates remain the default product experience).

### E8 — Documented conscious divergences (no code — a decision record)
Keep, with rationale, and record in the plan so future contributors don't "fix" them:
- **Custom `BaseAgent` routers + engine wrappers + the HITL interrogation loop** — ADK sanctions
  `BaseAgent` for bespoke control flow; v2's text-command protocol, deterministic reused engines
  (crawl/implement), and A0-proven pause/resume are exactly that. (Invariant I1.)
- **Client-driven gated orchestration** — the confirm-gates + HITL are a product requirement, not a
  limitation; that is why there is no in-agent coordinator on the default path.
- **Claude via LiteLlm** — explicit user decision (E2 makes it swappable, not removed).
- **Keeping the reused v1 engine** — the ~70% reuse is the whole point of the migration.

---

## 4. Sequencing, effort, risk

```
E2 (config) ─▶ E3 (tools) ─▶ E4 (callbacks)      … low-risk cleanups, any order
E5 (eval)   ─── builds on Plan B                 … highest value (adk eval)
E1 (agent.py+adk web) ─── after v1 shell drop    … coupled to the deploy milestone
E6 (Agent Engine) / E7 (coordinator) ─── optional, independent, opt-in
E8 ─── decision record, write once
```
- **Effort:** E1–E4 are S (cleanups); E5–E7 are M. Total ≈ one focused iteration on top of the current
  offline-green state.
- **Risk:** all E-milestones are additive/idiomatic and guarded by the existing offline suite (388
  passing). The only behavior-sensitive ones are E4 (callback rewrites — unit-test) and E7 (introduces
  an LLM-driven path — opt-in, fixture-gated).

## 5. Anti-goals (what this plan deliberately does **not** do)

- **Do not** convert the command-routers into an `LlmAgent + AgentTool` coordinator on the default
  path — it would make dispatch LLM-driven (breaks determinism I1), add an LLM call + latency +
  nondeterminism to every step, and break the text-command contract the MCP bridge speaks.
- **Do not** force Gemini (E2 keeps Claude-via-LiteLlm the default, just swappable).
- **Do not** replace Cloud Run + the MCP bridge with Agent Engine (E6 is an *additional* target; the
  bridge/MCP surface — invariant I4 — depends on the A2A `to_a2a` path).
- **Do not** rewrite the reused engines into `LlmAgent`s — they are deterministic Python by design.

---

## 6. One-paragraph recommendation

Adopt the **structural and tooling idioms** (E1 `agent.py`/`root_agent`/`adk web`, E2 `Config`, E3
plain-function tools, E5 canonical `eval/` + `adk eval`, E6 Agent-Engine deploy option) — these are
low-risk modernizations that make v2 look and run like a first-class ADK app and unlock the ADK CLI +
managed runtime. Add **E7 (optional autonomous coordinator)** as the one place the canonical
LLM-driven `AgentTool` orchestration earns its place, without touching the deterministic gated path.
**Consciously keep** the custom `BaseAgent` routers/engine-wrappers/HITL loop and Claude-via-LiteLlm
(E8) — these are justified by v2's constraints, and ADK's own guidance sanctions `BaseAgent` for
bespoke control flow. Net: v2 becomes idiomatic where it counts, while preserving the determinism,
the reused engine, and the human-in-the-loop product design the migration set out to protect.
