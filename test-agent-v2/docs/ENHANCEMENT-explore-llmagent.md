# Enhancement — the explore LLM steps as ADK `LlmAgent`s (give the `ModelProvider` its first live consumer)

The **executable plan** for the "reuse ADK more, on the agent aspect" enhancement in
`knowledge_gathering` (KGA). Today KGA is **100% custom `BaseAgent` + raw Vertex**: it uses *none* of
ADK's agent-reasoning primitives (`LlmAgent`, `output_schema`, `AgentTool`, `tools=`). This document
converts the two — and only two — LLM leaf-steps in the gather path (**hypothesize** and **external
leads**) into real ADK `LlmAgent`s, driven by the existing `GatherAgent`, with model access routed
through the `ModelProvider`. Nothing here touches `test-agent-v1`, the routers (D1), or the
interrogation store (D7).

> **Status: IMPLEMENTED 2026-09-08 (D15) — P0–P3 + P5.** `explore/schemas.py` + `hypothesize`/`ask_llm`
> as `LlmAgent(output_schema=…)` driven by `GatherAgent` via `agent_model()`; raw `complete()`/`_coerce_*`
> gone (`grep llm.vertex src/knowledge_gathering/explore` empty). **P4 deferred** (ctx-less loop shim; the
> loop is inert under the ADK GatherAgent — canary holds). Full integrated suite: 388 passed, 14 skipped.

Cross-refs: decisions **D1, D4, D5, D7, D10** ([`DECISIONS.md`](DECISIONS.md)); invariants **I1, I5,
I8** (§1 of [`IMPLEMENTATION-PLAN.md`](IMPLEMENTATION-PLAN.md), I8 in the cutover doc); the model
provider from [`ENHANCEMENT-adk-native-cutover.md`](ENHANCEMENT-adk-native-cutover.md) (C1/D10). This
enhancement **realizes D10's "Option B" for the explore steps** — the tracked follow-up of routing an
engine LLM call through the provider — and is the concrete trigger D4 anticipated
("`LessonRecallPlugin` is inert until/unless QuestionGen/etc. become real `LlmAgent`s").

---

## 0. Objective & the decision it turns on

Make KGA's two speculative-planning LLM calls **first-class ADK `LlmAgent`s** so that:

1. Model access goes through **`common/adk/providers` → `agent_model()`** (I8), giving the provider
   its **first live `LlmAgent` consumer** (today `agent_model()`/`claude_llm()` have **zero callers**
   in `src` — confirmed by grep; the cutover doc §1a records the same).
2. The bespoke **JSON-fence stripping + `_coerce_*` parsers** are deleted in favour of ADK
   `output_schema` (a pydantic `BaseModel`), which validates the structured output for us.
3. The `asyncio.to_thread(...)` offloads disappear — an `LlmAgent` is already async, so the two
   blocking `complete()` calls stop needing a thread hop (this is the same class of event-loop hazard
   that bit TPD implement; see the "serial Vertex calls → Cloud Run timeout" lesson).

**The turn-on decision (D15, proposed below):** convert **only the leaf enumerators**, keep
`GatherAgent` as the deterministic custom `BaseAgent` orchestrator that *drives* them, and keep the
whole thing **behind the existing opt-in flags** so the default gather path stays LLM-free and
deterministic (**I1**).

Non-negotiable boundary: this is **not** a router conversion (D1) and **not** a HITL-state migration
(D7). See §11.

---

## 1. Current state (grounded inventory)

The only LLM work in the entire KGA gather path is two files, both calling the raw Vertex transport
`common.llm.vertex.complete()` directly — bypassing ADK and the provider:

| Step | File | Flag (default) | Shape today | Consumed by |
|------|------|----------------|-------------|-------------|
| **Hypothesize** (G2) | `explore/hypothesize.py` | `KGA_LLM_HYPOTHESIZE` (**off**) | `hypothesize_terms(title, description, labels) -> str` (space-joined). Prompt → `complete()` → `_coerce_terms` flattens `{key_phrases, entities, subsystems}` | `explore/expand.py::expansion_round` via `asyncio.to_thread` |
| **External leads** (G4) | `explore/ask_llm.py` | `KGA_LLM_LEADS` (**off**) | `ask_llm_leads(title, description, labels) -> list[str]`. Prompt → `complete()` → `_coerce_leads` parses a JSON array | `expansion_round` via `asyncio.to_thread`, then **`ground_leads`** (deterministic, no LLM) |

Everything else in the fan-out is deterministic and stays deterministic: `ground_leads.py`,
`atlassian_search.py`, `self_seed.py`, `index.py`, `loop/crawl.py`, `loop/fetch/*`. The
`GatherAgent._run_async_impl` flow is: `_seed_probe` → `expansion_round` → `crawl` → summarize.

Two facts that shape the design:

- **`expansion_round` has a second caller** — `explore/loop.py` (the G5/A1 self-exploration loop),
  which is **opt-in and currently inert under the ADK `GatherAgent`** (the agent warns *"KGA_EXPLORE_LOOP
  is on but the explore-loop path is not yet ported to ADK (A1 follow-up); running the single-pass
  fan-out"*). The loop runs as plain async code with **no ADK `InvocationContext`**. This is why the
  planners can't simply live *inside* `expansion_round` as `LlmAgent`s — an `LlmAgent` needs a ctx to
  run under. See §5 and the P4 fallback.
- **`agent_model()` is unused.** No live `LlmAgent` exists anywhere in `src` (`grep -rn "LlmAgent("`
  → none). So this enhancement is additive: it introduces the first ones, on an opt-in path.

---

## 2. Target shape

`GatherAgent` (custom `BaseAgent`, unchanged role per D1) becomes the **orchestrator** that runs the
two planner `LlmAgent`s through its own `ctx`, reads their validated output from `session.state`, and
feeds the results into the **unchanged deterministic** `expansion_round` + `crawl`:

```
GatherAgent._run_async_impl(ctx)                         [custom BaseAgent — D1, unchanged role]
  seed, depth, repo = parse_input(text)
  probe = await _seed_probe(client, seed)                [deterministic]

  # NEW: opt-in ADK planners, run under the SAME ctx
  if KGA_LLM_HYPOTHESIZE and probe.title:
      ctx.session.state["kga_plan_in"] = {title, description, labels}
      async for _ in self.hypothesize_agent.run_async(ctx): pass
      terms = Hypothesis(**state["kga_hypothesis"]).as_terms() or probe.terms
  if KGA_LLM_LEADS and probe.title:
      async for _ in self.leads_agent.run_async(ctx): pass
      leads = Leads(**state["kga_leads"]).phrases

  new_seeds, md = await expansion_round(bank, client, seed=seed, terms=terms,
                                        leads=leads, allow_hypothesize=False, allow_leads=False, ...)
  result = await crawl(client, bank, seed, extra_seeds=new_seeds, ...)   [deterministic BFS — unchanged]

hypothesize_agent = LlmAgent(model=agent_model(max_tokens=400),          [NEW — ADK]
    output_schema=Hypothesis, output_key="kga_hypothesis",
    instruction=<the hypothesize prompt, templated from state>)
leads_agent       = LlmAgent(model=agent_model(max_tokens=400),          [NEW — ADK]
    output_schema=Leads, output_key="kga_leads",
    instruction=<the leads prompt, templated from state>)
```

`expansion_round` is refactored to **accept** `terms`/`leads` rather than calling the LLM itself; its
deterministic grounding (`ground_leads`, `atlassian_search_seeds`, `memory_self_seed`,
`semantic_self_seed`) is byte-for-byte the same. `hypothesize.py`/`ask_llm.py` shrink to: the pydantic
schema + the `LlmAgent` factory + the flag predicate; the prompt text moves verbatim into the
`LlmAgent.instruction`.

---

## 3. Decisions & reconciliations

### D15 (proposed) — Explore leaf LLM steps become `LlmAgent(output_schema=…)`, driven by `GatherAgent`, via the provider
- **Decision:** `hypothesize` and `ask_llm` become ADK `LlmAgent`s with a pydantic `output_schema`;
  `GatherAgent` runs them through `ctx` and reads `output_key` from `session.state`. Model =
  `agent_model()` (LiteLlm Claude). Raw `complete()` + `_coerce_*` + `_prompt` are deleted from these
  two files. The opt-in flags (`KGA_LLM_HYPOTHESIZE`, `KGA_LLM_LEADS`) are **unchanged and stay
  default-off**.
- **Why:** it is the smallest change that reuses ADK's *agent* machinery (not just its transport),
  gives the provider its first consumer (I8), and deletes hand-rolled JSON coercion. It is exactly the
  evolution D4 flagged and D10 tracked as "Option B".
- **Consequence:** with these two agents live under the Runner, `LessonRecallPlugin.before_model_callback`
  finally has an attach point for the explore prompts (grounded-lesson injection into planning becomes
  possible — a *follow-up*, not part of P0–P5). `output_schema` imposes ADK's "no tools / no transfer"
  constraint on these agents (fine — they are pure enumerators; see §5).
- **Status:** proposed; mirror into `DECISIONS.md` on adoption.

### Reconciliations (do not "fix" these)
- **D1 (routers stay deterministic `BaseAgent`s):** *upheld.* `KgaRouter` and `GatherAgent`'s
  orchestration are untouched as control flow — `GatherAgent` merely *drives* two leaf `LlmAgent`s. We
  are **not** converting a router to an `LlmAgent`+`AgentTool` coordinator, and dispatch stays
  deterministic.
- **D4 (cross-cutting logic in a Runner Plugin):** *upheld and advanced.* D4 says the recall/drain
  plugins are inert "until/unless … become real `LlmAgent`s". This is that moment for the explore
  path; the plugins keep working (they are `before_run`/`before_model` on the same Runner).
- **D5 → D10 (model via provider, Gemini removed):** *upheld.* The agents take `agent_model()`; no new
  model plumbing, no Gemini.
- **D7 (interrogation state stays in the bank, not ADK session state):** *upheld.* This enhancement
  only writes the planners' **transient** structured output to `session.state` under `output_key`
  (a scratch value re-derived every gather). It does **not** move any refine/define loop state into
  ADK state. See §11.

---

## 4. Invariants

- **I1 (determinism / one-LLM-call implement; default path is LLM-free):** *preserved by construction.*
  Both planners remain behind the existing default-off flags. With the flags off, the gather path makes
  **zero** LLM calls, exactly as today. The `crawl` BFS remains fully deterministic.
- **I5 (thinking-disabled + `max_tokens` survive the LiteLlm hop):** the planners set
  `agent_model(max_tokens=400)` (the current `_MAX_TOKENS`); the I5 gotchas live in the provider
  (D10), so they are inherited, not re-implemented.
- **I8 (model access only via the provider):** *this enhancement is a step toward completing I8* — it
  removes two of the raw-`complete()` call sites in favour of the provider. (The remaining engine
  callers — questions/understanding/distill — are out of scope; tracked separately as D10 Option B.)

---

## 5. ADK mechanics & gotchas

1. **`output_schema` ⇒ no tools, no transfer.** An ADK `LlmAgent` with `output_schema` set *cannot*
   also declare `tools=` and *cannot* transfer to other agents — it is a structured-reply leaf. This
   is exactly what the two enumerators are, so it costs nothing here, but it means these agents can
   never later gain tools without splitting the schema off. Document it so it isn't "fixed" later.
2. **Input via `session.state` + templated instruction.** The planners need the ticket `title`,
   `description`, `labels`. Put them in `ctx.session.state` before running, and use ADK instruction
   templating (`{key}` placeholders are filled from `session.state`) — or an `InstructionProvider`
   callable — so the prompt is assembled the ADK-native way rather than by f-string concatenation at a
   call site. Keep the prompt wording **verbatim** from today's `_prompt()` to preserve behaviour.
3. **Reading the result.** After `async for _ in agent.run_async(ctx): pass`, the validated object is
   in `ctx.session.state["kga_hypothesis"]` (a dict/JSON per `output_key`); re-wrap with the pydantic
   model to get typed access. Do **not** parse the event text.
4. **The loop caller has no ctx.** `explore/loop.py` runs outside a Runner, so it cannot call
   `agent.run_async(ctx)`. Since that path is opt-in **and** already inert under the ADK `GatherAgent`
   (A1), P4 keeps it working via a tiny provider-routed structured shim (Approach B, below) — no
   regression, no new agent needed there until A1 ports the loop into a real `BaseAgent`.
5. **LiteLlm + `output_schema` is prompt-enforced, not Gemini controlled-generation.** ADK realizes
   `output_schema` for non-Gemini models by instructing JSON + validating the reply. Keep
   `max_tokens` generous enough for the JSON (400 matched the old cap; bump if validation retries
   appear) and keep the "return ONLY JSON" wording.

> **Approach A vs B (recorded so the choice is legible):** *A* = the planners are real `LlmAgent`s
> driven by `GatherAgent` via ctx (this doc's recommendation — maximal agent-aspect, works wherever
> there is a ctx). *B* = route the existing imperative `complete()` calls through a
> `provider.generate_structured(prompt, schema)` helper (less "agent", but works even without a ctx,
> e.g. the loop). We adopt **A for the gather single-pass path** and use a **minimal B shim only for
> the ctx-less loop path** until A1 ports the loop.

---

## 6. Milestones (P0–P5)

- **P0 — Schemas.** Add `Hypothesis` and `Leads` pydantic `BaseModel`s (see §7). New file
  `knowledge_gathering/explore/schemas.py` (pydantic, unlike the stdlib-dataclass house style, because
  ADK `output_schema` requires a `BaseModel` — note this in the module docstring).
- **P1 — Planner agents.** In `hypothesize.py`/`ask_llm.py`, replace the `complete()` body with an
  `LlmAgent` factory (`build_hypothesize_agent()` / `build_leads_agent()`) using
  `agent_model(max_tokens=400)`, `output_schema`, `output_key`, and the **verbatim** prompt as
  `instruction` (templated from state). Delete `_coerce_*`, `_prompt`, and the `complete`/`vertex_config`
  imports. Keep `hypothesize_enabled()`/`leads_enabled()`.
- **P2 — `expansion_round` refactor.** Change the signature to accept `terms`/`leads` (pre-computed)
  and remove the internal `asyncio.to_thread(hypothesize_terms/ask_llm_leads, …)` calls; the
  deterministic grounding stays identical. `allow_hypothesize`/`allow_leads` become no-ops on this
  path (kept for the loop caller — P4).
- **P3 — `GatherAgent` orchestration.** Build the two agents once in `build_root_agent`/`GatherAgent`
  (as `sub_agents` for correct parent wiring), seed `session.state`, run them under `ctx` behind the
  flags, wrap the results with the schemas, and pass `terms=`/`leads=` into `expansion_round`.
- **P4 — Loop path (no regression).** Add the `provider.generate_structured(prompt, schema)` shim
  (Approach B) and have `explore/loop.py` use it where it previously relied on `expansion_round`'s
  inline hypothesize (only reachable with `KGA_EXPLORE_LOOP=1`, itself inert under the ADK gather
  today). Alternatively, gate the inline planning off in the loop until A1 — pick during execution and
  record it.
- **P5 — Tests & docs.** Repoint the unit tests (§10); add `test_planner_agents` (schema validation +
  fake-model wiring); update this doc's status and add D15 to `DECISIONS.md`.

---

## 7. Output schemas (sketch)

```python
# knowledge_gathering/explore/schemas.py  — pydantic (ADK output_schema requires BaseModel)
from __future__ import annotations
from pydantic import BaseModel, Field

class Hypothesis(BaseModel):
    """G2: the most distinctive search terms — key phrases, entities, subsystems (no ids/URLs)."""
    key_phrases: list[str] = Field(default_factory=list)
    entities:    list[str] = Field(default_factory=list)
    subsystems:  list[str] = Field(default_factory=list)

    def as_terms(self, cap: int = 8) -> str:
        seen: list[str] = []
        for s in (*self.key_phrases, *self.entities, *self.subsystems):
            s = (s or "").strip()
            if s and s not in seen:
                seen.append(s)
        return " ".join(seen[:cap])          # mirrors _coerce_terms + _MAX_TERMS

class Leads(BaseModel):
    """G4: at most ~6 speculative search phrases for related work elsewhere (no ids/URLs)."""
    phrases: list[str] = Field(default_factory=list, max_length=6)   # mirrors _MAX_LEADS
```

The `as_terms()` / dedup logic that used to live in `_coerce_terms`/`_coerce_leads` moves onto the
schema, so the LLM-parsing surface is a single validated model instead of tolerant hand-parsing.

---

## 8. Verification gates

- **[verify @P1] Provider is the model path.** `grep -rn "llm.vertex" src/knowledge_gathering/explore`
  returns **nothing** after P1 (both raw callers gone); the agents build with `agent_model()`.
- **[verify @P3] Default path unchanged (I1).** With both flags off, a gather makes **zero** LLM calls
  and produces the same nodes/inventory as `master` for a fixed seed (equivalence test).
- **[verify @P3] Flag-on parity.** With `KGA_LLM_HYPOTHESIZE=1`, a recorded/fake model returning the
  same JSON yields the **same promoted seeds** as the old `hypothesize_terms` path (behavioural parity,
  not just "it runs").
- **[verify @P5] No live-model tests.** All planner tests inject a fake ADK model (no network), same as
  the existing offline suite (Starlette TestClient + recorded Atlassian + FakeBucket).
- **[verify @P5] Schema rejects junk.** A malformed model reply fails `output_schema` validation and
  degrades to `probe.terms` / `[]` (best-effort contract preserved — the old code returned `""`/`[]`
  on bad JSON).

---

## 9. Rollback

Single-file-scoped and reversible: restore `hypothesize.py`/`ask_llm.py` to the `complete()` bodies
and revert the `expansion_round` signature. Because the feature sits behind default-off flags, a bad
deploy has **no effect on the default gather path** — the blast radius is only `KGA_LLM_*=1` runs.

---

## 10. Test repoint

Existing tests that touch these units (per the cutover doc §Step-4 test map): `test_hypothesize`,
`test_ground_leads`, `test_atlassian_search`, `test_explore`, `test_loop`. Changes:

- `test_hypothesize` — assert against the `Hypothesis` schema + a fake ADK model returning the JSON,
  instead of monkeypatching `complete`. Keep the "no usable terms → keeps probe terms" case.
- `test_ground_leads` — **unchanged** (it never called the LLM; it grounds a supplied `leads` list).
- `test_explore` — the `test_explore_loop_flag_is_inert_in_adk_gather` canary must still pass (A1
  fence intact); add coverage for the P4 shim if Approach B is used there.
- New `test_planner_agents` — schema validation + `GatherAgent` reads `output_key` from state.

---

## 11. Non-goals & tracked follow-ups

- **Do NOT move interrogation/HITL state to ADK `session.state`.** Rejected by **D7** (the bank
  persistence carries insights/decisions/questions + B0–B6 and is already tested; re-porting is risk
  for no gain). This enhancement's only use of `session.state` is the planners' transient `output_key`
  scratch value.
- **Do NOT convert `KgaRouter`/`GatherAgent` orchestration to an `LlmAgent` coordinator.** Rejected by
  **D1** (breaks I1 + the bridge's deterministic text contract).
- **Do NOT agent-ify `crawl`/`fetch_node`.** Deterministic bounded I/O; an LLM here forfeits the
  `max_nodes`/`max_seconds` guarantees.
- **Follow-up — read tools as `FunctionTool`s.** The read-only memory tools in `common/adk/tools.py`
  are already ADK-shaped functions but are dispatched by string parsing in `KgaRouter._read_tool`.
  Exposing them as `FunctionTool`s on an `LlmAgent` is only worthwhile if NL memory access is a
  product goal (it inserts an LLM into a currently-deterministic command). Deferred.
- **Follow-up — grounded-lesson injection into planning.** Once the planners are live `LlmAgent`s,
  `LessonRecallPlugin.before_model_callback` can inject recalled lessons into the hypothesize/leads
  prompt (D4). Deferred.
- **Adjacent — A1 explore-loop port.** Porting `explore/loop.py` into an ADK `BaseAgent` is separate
  (loop control, not an `LlmAgent` conversion) and is tracked as the A1 follow-up; when it lands, the
  same planner `LlmAgent`s from P1 drive it and the P4 shim retires.
