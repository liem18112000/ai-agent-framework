# Enhancement — the TPD generators as ADK `LlmAgent`s (make the `ModelProvider` authoritative for define/implement generation)

The **executable plan** for the "reuse ADK more, on the agent aspect" enhancement in
`test_plan_definition` (TPD). Like KGA (see [`ENHANCEMENT-explore-llmagent.md`](ENHANCEMENT-explore-llmagent.md)),
TPD today is **100% custom `BaseAgent` + raw Vertex**: it uses *none* of ADK's agent-reasoning
primitives. But TPD is a **richer** target — it has **five** structured LLM generators (define
questions, brief, implement test-data/scenarios/steps), each calling `common.llm.vertex.complete()`
and hand-parsing the reply with `loads_array`/`coerce_str`. This document converts them to ADK
`LlmAgent`s with `output_schema`, driven by the existing `DefineAgent`/`ImplementAgent`, with model
access routed through the `ModelProvider` — **without** breaking the I3 one-call implement budget,
D1 (routers stay deterministic), D6 (reuse the engine), or D7 (interrogation store stays in the bank).

> **Status: IMPLEMENTED 2026-09-08 (D16) — T0–T5.** Implement generators (`scenarios` + detail-gated
> `test_data`/`steps`) as `LlmAgent(output_schema=…)` via `agent_model()`; `implement_plan` async; raw
> `complete()`/`loads_array` gone from the implement `llm/*`. **I3 preserved** — default implement = 1
> LLM call, `detail` = 3 (call-count tests lock it). **T6 deferred** (QuestionGen/brief via the shared
> `common/adk/interrogation.py` — coordinated with KGA; a follow-up). Full suite: 388 passed, 14 skipped.

Cross-refs: decisions **D1, D4, D6, D7, D10** ([`DECISIONS.md`](DECISIONS.md)); invariants **I1
(determinism), I3 (implement = 1 LLM call, off the event loop), I5 (thinking/max_tokens survive
LiteLlm), I8 (model only via the provider)** (§1 of [`IMPLEMENTATION-PLAN.md`](IMPLEMENTATION-PLAN.md));
the model provider (C1/D10, [`ENHANCEMENT-adk-native-cutover.md`](ENHANCEMENT-adk-native-cutover.md)).
This enhancement is the concrete execution of what **IMPLEMENTATION-PLAN §refine_agent** and **D4**
already named — *"QuestionGen/Understanding/Scenario `LlmAgent`s + heuristic fallback"* — which the
as-built code never realized (the generation stayed in the reused v1 engine as raw Vertex).

---

## 0. Objective & the decision it turns on

Make TPD's define/implement generators **first-class ADK `LlmAgent`s** so that:

1. Model access goes through **`common/adk/providers` → `agent_model()`** (I8) — giving the provider
   its **first live consumer in TPD** (today `agent_model()`/`claude_llm()` have **zero callers** in
   `src/test_plan_definition`, confirmed by grep).
2. The five copies of `loads_array(...)` + per-field `it.get(k)` coercion are replaced by ADK
   `output_schema` (pydantic `BaseModel`s), which validate + type the structured output for us.
3. The generators become **async**, so the `asyncio.to_thread(implement_plan, …)` hop in
   `ImplementAgent` (and the blocking `complete()` inside it) stop being an event-loop hazard — the
   exact class of bug behind the "implement serial Vertex calls → Cloud Run timeout" incident that
   **I3** exists to prevent.

**The turn-on decision (D16, proposed below):** convert the generators to `LlmAgent`s **leaf-first**,
keep `DefineAgent`/`ImplementAgent`/`TpdRouter` as deterministic custom `BaseAgent`s that *drive*
them, and — critically — **preserve the I3 budget**: the default implement path still makes **exactly
one** LLM call (scenarios), with test-data/steps LLM generation staying behind `detail`/
`TPD_LLM_DETAIL`.

---

## 1. Current state (grounded inventory)

Every LLM call in TPD is a raw `common.llm.vertex.complete()` that returns text, parsed with
`common/llm/parse.py::loads_array` (the TPD counterpart of KGA's `_coerce_*`). Five generators:

| # | Generator | File | Stage / trigger | `max_tokens` | Parse → type |
|---|-----------|------|-----------------|--------------|--------------|
| 1 | `claude_plan_questions` | `llm/questions.py` | **define**, per round; on when `vertex_config()` set (heuristic fallback) | 6000 | `loads_array`+`coerce_str` → `Question` |
| 2 | `claude_brief` | `llm/plan.py` | **define**, finalize (the `restater`) | 700 | plain text → brief string |
| 3 | `claude_test_data` | `llm/testdata.py` | **implement**; gated `detail or TPD_LLM_DETAIL` | 6000 | `loads_array` → `TestData` |
| 4 | `claude_scenarios` | `llm/scenarios.py` | **implement**; on when `vertex_config()` set = **the I3 "one call"** | 6000 | `loads_array` → `TestScenario` |
| 5 | `claude_steps` | `llm/steps.py` | **implement**; gated `detail or TPD_LLM_DETAIL`; **batched** (`_STEP_BATCH=8`) | 8000 | `loads_array` → `TestStep` |

Call-site depth (this is what makes TPD harder than KGA):

- **Define generators (1, 2)** are buried in the **reused v1 engine**: `claude_plan_questions` is
  wrapped by `define/questions.py::make_generator` into a sync `Callable[[Pack, str], list[Question]]`
  and invoked by `PlanSession.next_questions` → `common.interrogate.questions.generate_round`;
  `claude_brief` is the `restater` in `PlanSession.finalize`. **`PlanSession` is driven by the shared
  `common/adk/interrogation.py::InterrogationAgent`, which KGA refine also uses** — so touching the
  generator seam is a *common-level* change affecting both agents.
- **Implement generators (3, 4, 5)** are called inside `implement/generate.py::implement_plan` (a
  **sync** orchestrator that interleaves LLM calls with `store.write_*` + index updates), which
  `ImplementAgent` runs via `asyncio.to_thread`.

Two facts shape the design (identical to KGA): **`agent_model()` has no consumer** (this adds the
first), and **`InterrogationAgent` already emits `state_delta`** but the pause/resume state lives in
the **bank**, not ADK state (D7 — do not change).

---

## 2. Target shape

Leaf-first. `ImplementAgent`/`DefineAgent` stay deterministic custom `BaseAgent`s (D1) and *drive*
the generator `LlmAgent`s through their `ctx`, reading validated output from `session.state`:

```
ImplementAgent._run_async_impl(ctx)                         [custom BaseAgent — D1]
  plan = store.read_plan(bank, ctx_id)                      [deterministic]
  # test-data: heuristic by default (I3); LlmAgent only under detail/TPD_LLM_DETAIL
  test_data = detail ? await run(testdata_agent, ctx) : heuristic_test_data(...)
  # scenarios: THE one default LLM call (I3) — now an LlmAgent
  scenarios = await run(scenario_agent, ctx) or heuristic_scenarios(...)   [fallback on invalid]
  # steps: heuristic by default (I3); LlmAgent only under detail
  steps = detail ? await run(steps_agent, ctx, batched) : heuristic_steps(...)
  store.write_*(...) ; export_features(...) ; index updates        [deterministic — unchanged]

scenario_agent = LlmAgent(model=agent_model(max_tokens=6000),           [NEW — ADK, flagship]
    output_schema=Scenarios, output_key="tpd_scenarios",
    instruction=<scenarios_prompt, templated from state>)
# testdata_agent / steps_agent — same shape, DETAIL-gated so I3's default 1-call budget holds
```

`implement_plan` is refactored from sync to **async** (it already lives behind an `await` in
`ImplementAgent`); the deterministic store/index work stays synchronous. The `llm/*.py` modules
shrink to: the pydantic schema + the `LlmAgent` factory + the prompt-as-`instruction`; `loads_array`
usage in TPD is deleted.

The **define generators (1, 2)** are the cross-cutting stretch (T6): converting `claude_plan_questions`
to a QuestionGen `LlmAgent` means the shared `InterrogationAgent` runs it through `ctx` and feeds the
result into `generate_round` — the D4-named "QuestionGen becomes a real `LlmAgent`" move, which also
activates `LessonRecallPlugin.before_model_callback` for interrogation. Because it touches
`common/`, it is scoped **after** the TPD-local implement conversions and coordinated with KGA refine.

---

## 3. Decisions & reconciliations

### D16 (proposed) — TPD generators become `LlmAgent(output_schema=…)`, leaf-first, via the provider, preserving I3
- **Decision:** the implement generators (`scenarios` flagship; `test_data`/`steps` detail-gated)
  become ADK `LlmAgent`s with pydantic `output_schema`, driven by `ImplementAgent` through `ctx`.
  Model = `agent_model()`. Raw `complete()` + `loads_array` are deleted from the TPD `llm/*` modules.
  The **define** generators (`claude_plan_questions`, `claude_brief`) are converted in the same style
  but as a **cross-cutting** step (T6) because they run inside the shared `InterrogationAgent`.
- **Why:** smallest change that reuses ADK's *agent* machinery, gives the provider its first TPD
  consumer (I8), and deletes five hand-parsers — while honouring the reused-engine boundary (D6) by
  only lifting the LLM *leaf*, not the orchestration.
- **Consequence:** `output_schema` imposes ADK's "no tools / no transfer" on these agents (fine — they
  are pure generators). With the generators live, `LessonRecallPlugin` gains a real attach point
  (D4). **I3 is explicitly preserved:** default implement = 1 LLM call; detail-gated generators do not
  run by default.
- **Status:** proposed; mirror into `DECISIONS.md` on adoption. Parallels KGA's **D15**.

### Reconciliations (do not "fix" these)
- **D1 (routers stay deterministic):** *upheld.* `TpdRouter`/`DefineAgent`/`ImplementAgent` keep their
  deterministic control flow; they only *drive* leaf `LlmAgent`s. No `LlmAgent` coordinator.
- **D4 (cross-cutting logic in a Runner Plugin):** *upheld and advanced.* This is the "QuestionGen/
  Scenario become real `LlmAgent`s" trigger D4 named; the plugins keep working on the same Runner.
- **D6 (reuse the v1 engine ~unchanged):** *honoured.* Only the LLM leaf is lifted out; `PlanSession`,
  `implement_plan`'s store/index logic, the heuristics, `render/`, `pack.py`, `memory/` are untouched.
- **D7 (interrogation state stays in the bank):** *upheld.* Nothing moves `PlanSession` state into ADK
  `session.state`; the only state use is the generators' transient `output_key` scratch value.
- **D10/I8 (model via provider, Gemini gone):** *upheld.* Generators take `agent_model()`; no new
  plumbing.

---

## 4. Invariants

- **I3 (implement default = 1 LLM call, off the event loop, within Cloud Run timeout):** *the
  load-bearing constraint here.* Preserved by construction — only `scenarios` runs by default;
  `test_data`/`steps` `LlmAgent`s stay behind `detail`/`TPD_LLM_DETAIL`. A **call-count assertion
  test** (already mandated by I3) guards it. Making the pipeline async *helps* the "off the event
  loop" clause — an `LlmAgent` `await` never blocks the loop the way the thread-wrapped `complete()`
  did.
- **I1 (determinism):** *preserved.* The LLM stays a leaf; Python drives step order; no autonomous
  tool-loop.
- **I5 (thinking-disabled + `max_tokens` survive LiteLlm):** each generator sets its current
  `max_tokens` (6000/8000/700) via `agent_model(max_tokens=…)`; the I5 gotchas live in the provider.
- **I8 (model only via the provider):** advanced — five raw-`complete()` sites removed. (The
  remaining common engine callers are tracked as D10 Option B.)

---

## 5. ADK mechanics & gotchas

1. **`output_schema` ⇒ no tools, no transfer.** Same constraint as KGA: an `LlmAgent` with
   `output_schema` is a structured-reply leaf — it cannot use `tools=` or transfer. Fine for pure
   generators (identical constraint to the KGA planners, §5.1 of the KGA doc).
2. **JSON *array* vs object.** Four of the five generators return a JSON **array** of records
   (`Question`/`TestData`/`TestScenario`/`TestStep`). ADK `output_schema` wants a `BaseModel`, so wrap
   the list: `class Scenarios(BaseModel): items: list[ScenarioItem]` and read `.items`. This mirrors
   what `loads_array` did, but validated.
3. **Heuristic fallback must survive.** Every TPD generator falls back to a heuristic on empty/invalid
   output. Keep that: on `output_schema` validation failure, degrade to `heuristic_scenarios` /
   `heuristic_test_data` / `generate_steps` — do **not** raise. This preserves the current best-effort
   contract and the coverage-matrix behaviour.
4. **Batched steps.** `claude_steps` runs in `_STEP_BATCH=8` chunks. Keep the batching: run the steps
   `LlmAgent` once per chunk (still only under `detail`), or pass the batch in state and let one run
   return all — but do not collapse batching in a way that blows `max_tokens=8000`.
5. **Input via `session.state` + templated instruction.** Put the plan/pack summary/test-data into
   `ctx.session.state`; use ADK `{key}` instruction templating (or an `InstructionProvider`) so the
   existing `prompts.py` text becomes the `instruction` verbatim. After
   `async for _ in agent.run_async(ctx): pass`, read `ctx.session.state[output_key]` and re-wrap with
   the schema — do not parse event text.
6. **The shared `InterrogationAgent` seam (T6).** `generate_round(pack, rnd, generator=…)` expects a
   **sync** `Callable`. Converting `claude_plan_questions` to an `LlmAgent` means `InterrogationAgent`
   must run it through `ctx` *before* `generate_round` and pass the questions in — a change in
   `common/adk/interrogation.py` that **KGA refine also rides on**. Do T6 as a joint common change with
   a parity test for both agents, after the TPD-local T1–T4.

---

## 6. Milestones (T0–T6)

- **T0 — Schemas.** Add `test_plan_definition/llm/schemas.py` (pydantic): `Scenarios`, `TestDataList`,
  `StepsList`, and (T6) `PlanQuestions`. Note in the docstring that pydantic is required by ADK
  `output_schema` (the rest of TPD is stdlib dataclasses).
- **T1 — ScenarioGen `LlmAgent` (flagship).** Replace `claude_scenarios`' `complete()` body with
  `build_scenario_agent()` (`agent_model(max_tokens=6000)`, `output_schema=Scenarios`,
  `output_key="tpd_scenarios"`, verbatim `scenarios_prompt` as `instruction`). Delete its `loads_array`.
- **T2 — Async implement pipeline.** Make `implement_plan` async; have `ImplementAgent` `await` it
  directly (drop the `asyncio.to_thread` wrapper) and run the scenario agent via `ctx`. Keep all
  `store.write_*`/index/`export_features` calls synchronous. **Add/keep the I3 call-count test.**
- **T3 — Detail-gated test-data + steps agents.** Convert `claude_test_data` and `claude_steps` to
  `LlmAgent`s that run **only** under `detail`/`TPD_LLM_DETAIL` (preserve the batching for steps).
  Verify the default path still makes exactly one LLM call.
- **T4 — Delete the raw seam (TPD-local).** Remove `common.llm.vertex` imports from the implement
  `llm/*` modules; `grep` proves no raw `complete()` in the implement path.
- **T5 — Tests & docs (implement side).** Repoint `test_plan_llm.py`/`test_plan_implement.py`/
  `test_adk_tpd.py` to fake-model wiring; add `test_scenario_agent`; record D16 in `DECISIONS.md`.
- **T6 — (cross-cutting stretch) QuestionGen + brief as `LlmAgent`s.** Convert `claude_plan_questions`
  (and optionally `claude_brief`) via the shared `InterrogationAgent` seam (§5.6); add the KGA-refine
  parity test; this activates `LessonRecallPlugin` for interrogation. Coordinate with KGA's D15 work.

---

## 7. Output schemas (sketch)

```python
# test_plan_definition/llm/schemas.py — pydantic (ADK output_schema requires BaseModel)
from __future__ import annotations
from pydantic import BaseModel, Field

class ScenarioItem(BaseModel):
    id: str = ""; title: str = ""; kind: str = ""; methodology: str = ""
    description: str = ""; rationale: str = ""
    preconditions: list[str] = Field(default_factory=list)
    data_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)

class Scenarios(BaseModel):
    items: list[ScenarioItem] = Field(default_factory=list)   # replaces loads_array + _FIELDS pick

class TestDataItem(BaseModel):
    id: str; kind: str; spec: dict = Field(default_factory=dict)
    source_refs: list[str] = Field(default_factory=list)

class TestDataList(BaseModel):
    items: list[TestDataItem] = Field(default_factory=list)

class StepItem(BaseModel):
    scenario_id: str
    steps: list[dict] = Field(default_factory=list)           # {order, keyword, action, expected}

class StepsList(BaseModel):
    items: list[StepItem] = Field(default_factory=list)
```

The per-field `it.get(k)` mapping + `setdefault`/`coerce_str` logic (created_at, plan_id, default
kind/methodology) moves into a small typed `.to_models(plan, now)` adapter on each schema, so the
LLM-parsing surface is one validated model instead of five tolerant hand-parsers.

---

## 8. Verification gates

- **[verify @T2] I3 preserved.** A default `implement` (no `detail`, no `TPD_LLM_DETAIL`) makes
  **exactly one** LLM call (the scenario agent); a call-count assertion test locks it. Detail on →
  three calls (test-data + scenarios + steps-per-batch).
- **[verify @T4] Provider is the model path.** `grep -rn "llm.vertex" src/test_plan_definition/llm`
  is empty for the implement generators; agents build with `agent_model()`.
- **[verify @T3] Fallback intact.** A fake model returning invalid JSON degrades to the heuristic
  scenarios/test-data/steps (best-effort contract), not an exception.
- **[verify @T5] Offline.** All generator tests inject a fake ADK model — no network (Starlette
  TestClient + FakeBucket, as today).
- **[verify @T6] Interrogation parity.** With QuestionGen as an `LlmAgent`, both TPD define and KGA
  refine produce the same rounds/questions as `master` for a fixed pack (shared-seam parity).

---

## 9. Rollback

Scoped and reversible. T1–T4 are TPD-local: restore the `llm/*` `complete()` bodies and revert
`implement_plan` to sync. Because the risky generators (test-data/steps) stay behind default-off
gates and the scenario agent falls back to the heuristic, a bad deploy cannot break the default
implement path. T6 (common seam) rolls back independently by restoring the sync `generator` callable.

---

## 10. Test repoint

- `test_plan_llm.py` — the main target: assert against the schemas + a fake ADK model instead of
  monkeypatching `complete`. Keep the "unparseable → heuristic fallback" cases.
- `test_plan_implement.py` — add the **I3 call-count** assertion (default = 1); exercise `detail` = 3.
- `test_adk_tpd.py` — `ImplementAgent` reads `output_key` from state; async pipeline.
- `test_plan_define_loop.py` / `test_refine_questions.py` — only touched by T6 (QuestionGen seam);
  add the cross-agent parity test there.
- `test_plan_scaffold.py` / `test_plan_gherkin.py` — unchanged (heuristic/render paths).

---

## 11. Non-goals & tracked follow-ups

- **Do NOT move `PlanSession` state to ADK `session.state`.** Rejected by **D7**; the bank persistence
  carries decisions/questions/gaps + B0–B6 and is tested. Only the generators' transient `output_key`
  touches ADK state.
- **Do NOT convert `TpdRouter`/`DefineAgent`/`ImplementAgent` to an `LlmAgent` coordinator.** Rejected
  by **D1** (breaks I1 + the bridge's deterministic text contract).
- **Do NOT run the detail generators by default.** Rejected by **I3** — it is the whole point of the
  `TPD_LLM_DETAIL` gate (see the "serial Vertex calls → Cloud Run timeout" lesson).
- **Do NOT agent-ify** the heuristics, `render/gherkin.py`, `pack.py`, `memory/writers.py`, or the
  index projection — deterministic by design.
- **Follow-up — `claude_brief` as an `LlmAgent`.** Returns free text (no `output_schema`); low value,
  bundle with T6 or leave provider-routed.
- **Follow-up — grounded-lesson injection.** Once QuestionGen/ScenarioGen are live `LlmAgent`s,
  `LessonRecallPlugin.before_model_callback` can inject recalled lessons into their prompts (D4).
- **Coordinate with KGA.** T6 shares `common/adk/interrogation.py` with KGA refine; sequence it with
  the KGA planner work (D15 / [`ENHANCEMENT-explore-llmagent.md`](ENHANCEMENT-explore-llmagent.md)).
