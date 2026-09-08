# test-agent-v2 — detailed implementation plan

The executable build guide for the ADK rebuild. It turns the design in
[`../../docs/adk-transform/`](../../docs/adk-transform/) into concrete milestones — files to create,
code shapes, test gates, and done-criteria — for building **`test-agent-v2/`** from the
**`test-agent-v1/`** baseline.

- **Design rationale** (why each mapping): `../../docs/adk-transform/01-mapping.md`.
- **Per-agent target graphs**: `02-plan-testing-agents.md` (Plan A), `03-plan-test-evaluation.md` (Plan B).
- **Concrete code stubs referenced below**: [`code-skeletons.md`](code-skeletons.md).
- **Risks / rollback**: `../../docs/adk-transform/04-roadmap-risks.md`.

> Convention: paths are relative to `test-agent-v2/` unless prefixed. `[copy]` = lift verbatim from
> `test-agent-v1/`; `[new]` = write fresh; `[rewrite]` = ADK replacement of a v1 shell module.

---

## 0. Objective

Ship KGA + TPD as **ADK agent graphs** (Plan A) and the evaluator on **`adk eval`** (Plan B), such
that the MCP tools Claude Code calls behave identically to v1, on the same Cloud Run + Cloud SQL +
GCS runtime, with Claude Sonnet 5 via LiteLlm.

## 1. Invariants — the guardrails CI must protect

These are non-negotiable; every milestone's test gate exists to defend one of them. A change that
violates an invariant is a bug, not a tradeoff.

| # | Invariant | Enforced by |
|---|-----------|-------------|
| I1 | **Determinism** — Python drives control flow; the LLM is a leaf, never picks the next step | agent graphs use workflow/`BaseAgent`; no autonomous tool-loop; code review + trajectory eval |
| I2 | **B0–B6 de-bias gates intact** — run-scoped pack, IDF hub-penalty, structural grounding, `scope='shared'` semantic recall | reused engine modules unchanged; bleed-fixture leak test (`hard_negative_leak==0`) |
| I3 | **`implement` default = 1 LLM call**, whole thing off the event loop, within Cloud Run timeout | `TPD_LLM_DETAIL` gate preserved; call-count assertion test |
| I4 | **MCP surface + bridge unchanged** — same tool names/signatures, same `test` prompt | skill-parity test; bridge reused verbatim from v1 |
| I5 | **Claude via LiteLlm, thinking disabled, max_tokens honored** | centralized `claude_llm()`; a live "disabled-thinking + full-length JSON parses" test |
| I6 | **No cross-agent imports; `common` never imports an agent** | import-linter / a grep gate in CI (same rule as v1) |
| I7 | **Heuristic fallback everywhere the LLM is optional** — `vertex_config()` unset ⇒ fully deterministic | reused engine; a "Vertex-off" smoke run |

## 2. Target directory layout

```
test-agent-v2/
├─ pyproject.toml                 [rewrite]  + google-adk>=1.22, litellm ; scripts unchanged
├─ Dockerfile                     [rewrite]  agent CMD → the to_a2a app ; bridge CMD unchanged
├─ .env .dockerignore .gitignore  [copy]
├─ docs/                          [new]      this plan
├─ src/
│  ├─ common/                     [copy]  the framework-neutral engine — the ~70% reuse
│  │  ├─ memory/ learn/ interrogate/ llm/ atlassian/ codegraph/ extract/ models/   [copy verbatim]
│  │  ├─ db.py monitoring.py      [copy verbatim]
│  │  ├─ memory/factory.py        [new]   build_bank() lifted out of the a2a-importing executor.py
│  │  ├─ card.py taskstore.py executor.py ops.py middlewares/   [DROP — replaced by common/adk/*]
│  │  ├─ bridge/                  [copy]  client-side MCP↔A2A bridge — unchanged (I4)
│  │  └─ adk/                     [new]   the ADK substrate (see §4 A.0 + code-skeletons.md)
│  │     ├─ model.py services.py plugins.py serve.py tools.py interrogation.py
│  ├─ knowledge_gathering/
│  │  ├─ loop/ explore/ models/ monitoring.py   [copy verbatim]  the crawl/explore engine
│  │  ├─ bridge/                  [copy]  MCP bridge unchanged (I4)
│  │  ├─ agent.py                 [rewrite]  builds the ADK root agent (was: A2A AgentCard + skills)
│  │  ├─ adk_app.py               [new]   `app = serve(root_agent, REQUIRED_ENV)`  (was: server.py)
│  │  ├─ agents/                  [new]   gather_agent.py, refine_agent.py
│  │  └─ executor/                [DROP — replaced by agents/ + the ADK runner]
│  ├─ test_plan_definition/
│  │  ├─ define/ implement/ llm/ memory/ models/ render/ pack.py monitoring.py  [copy verbatim]
│  │  ├─ bridge/                  [copy]  unchanged (I4)
│  │  ├─ agent.py                 [rewrite]   ADK root agent
│  │  ├─ adk_app.py               [new]
│  │  ├─ agents/                  [new]   define_agent.py, implement_agent.py
│  │  └─ executor/                [DROP]
│  └─ test_evaluation/            [Plan B — see §4 B]
│     ├─ metrics/ golden/ golden_plans/ models.py golden.py   [copy verbatim]  the scoring math
│     ├─ engine.py plan_engine.py [copy]   still callable by the runtime MCP tool
│     ├─ eval/                    [new]   evalsets/*.evalset.json + test_config.json + custom metrics
│     └─ adk_app.py               [new]
└─ tests/                         [copy + extend]  v1 suite + ADK-equivalence + parity tests
```

## 3. Engine reuse strategy (the ~70%)

The neutral engine imports no framework, so it moves verbatim. **The only source edit** is I5-safe:
lift `build_bank()` out of the a2a-importing `common/executor.py` into `common/memory/factory.py`
(the rest of `executor.py` — the A2A `reply()`/`now()` — is dropped, replaced by ADK `Event`s).

- **Copy mechanism (M0):** `git mv`-style copy of `test-agent-v1/src/common/{memory,learn,interrogate,
  llm,atlassian,codegraph,extract,models,db.py,monitoring.py,bridge}` and the two agents'
  engine subpackages (listed in §2) into `test-agent-v2/src/…`.
- **Proof the copy is faithful:** the copied engine must pass v1's *neutral* unit tests unchanged
  (`test_memory`, `test_learn`, `test_interrogate*`, `test_atlassian*`, `test_codegraph`,
  `test_extract`, `test_pg_*`, `test_retrieve_facade`, `test_graph_index`, …). Run them in v2 as-is.
- **Sync during transition:** while both versions live, treat v1's engine as upstream; any v1 engine
  fix is cherry-picked into v2. (Post-cutover, promote the engine to a shared installable package —
  out of scope for this plan; tracked as a follow-up.)

---

## 4. Milestones

Each milestone is independently shippable behind the unchanged bridge. Format: **Goal · Files ·
Shapes · Gate · DoD**. Code shapes are stubbed in [`code-skeletons.md`](code-skeletons.md).

### M0 — Project scaffold + engine copy
- **Goal:** a v2 project that installs, lints, and serves a trivial ADK agent over A2A behind the
  same bearer + health, with the copied engine passing its unit tests.
- **Files:** `pyproject.toml` [rewrite] (add `google-adk>=1.22`, `litellm`; keep `a2a-sdk` for
  `to_a2a`'s A2A layer + the bridge; keep the `bridge`/`dev`/`eval` extras), `Dockerfile` [rewrite],
  copy the engine (§3), `common/memory/factory.py` [new], a throwaway `hello_agent` + `adk_app.py`.
- **Gate:** `ruff` clean; copied-engine unit tests green; `curl /livez` 200, `/.well-known/agent-card.json`
  served by `to_a2a`; bearer 401 without token.
- **DoD:** `uvicorn knowledge_gathering.adk_app:app` boots; the v1 MCP bridge (pointed at it) lists tools.
- **Size:** M.

### A0 — HITL pause/resume spike (de-risk — do before A.0)
- **Goal:** settle the one genuine unknown (R1 in the risk register): can a multi-round human-in-the-loop
  interrogation pause and resume cleanly on ADK? Prove **Option B** (custom `BaseAgent` that
  checkpoints loop state into ADK session `state`, emits the round, ends the invocation; next turn
  reads state back and advances) round-trips a 3-round dialogue with `DatabaseSessionService`.
- **Also:** a throwaway probe of **Option A** (`LongRunningFunctionTool` inside a `SequentialAgent`)
  to confirm/deny the known resume bugs (#3348/#5349/#3184/#5064) on the pinned `google-adk`.
- **Files:** `spikes/hitl_option_b.py`, `spikes/hitl_option_a.py` (throwaway, not shipped — **removed
  after verification**; the confirmed facts live in §9 and Option B ships as `common/adk/interrogation.py`).
- **Gate:** Option B: 3 rounds, state intact across simulated restarts, no re-execution of prior
  rounds. Decision recorded: default = Option B (adopt A only if the probe is clean).
- **DoD:** a one-paragraph decision note appended to `04-roadmap-risks.md`.
- **Size:** S. **Blocks A.0/A1/A2.**
- **✅ STATUS: DONE (2026-09-07).** Option B **passed** on `google-adk 2.8.0` (3 rounds paused/resumed
  in order, state survived a simulated `DatabaseSessionService` restart, no round re-executed) →
  RefineAgent/DefineAgent use Option B. Option A left model-gated (not needed). The spike dir was
  **removed post-verification**; the confirmed ADK-2.x API facts are retained in §9.

### A.0 — `common/adk/` shared foundation
- **Goal:** the substrate every v2 agent uses. See [`code-skeletons.md`](code-skeletons.md) for full stubs.
- **Files [new]:**
  - `model.py` — `claude_llm()` → `LiteLlm("vertex_ai/claude-sonnet-5")` with **thinking disabled +
    max_tokens** wired one place (I5). Falls back to None when `vertex_config()` unset (I7).
  - `services.py` — `build_runner(agent)`: `DatabaseSessionService` on `common/db.py`'s engine
    (fallback `InMemorySessionService`), optional `GcsArtifactService`.
  - `plugins.py` — `LearnDrainPlugin` (`before_run_callback` = `learn.drain` + `maybe_drain_index`,
    off-path) and `LessonRecallPlugin` (`before_model_callback` = inject grounded lessons) (I2).
  - `serve.py` — `serve(root_agent, required_env)`: `to_a2a(root_agent)` → wrap with
    `BearerAuthMiddleware` + `make_health_routes` → uvicorn app. Replaces v1 `server.py`+`card.py`.
  - `tools.py` — reusable `FunctionTool`s: `search_memory`, `get_note`, `search_lessons`,
    `veto_lesson`, `recall_lessons`, `atlassian_*`, `build_codegraph`.
  - `interrogation.py` — the `InterrogationAgent(BaseAgent)` base (Option B) shared by refine + define.
- **Gate:** skill-parity test — the `to_a2a` card advertises the skill ids the bridge/tests expect (I4);
  `claude_llm()` disabled-thinking test parses a full-length questions array (I5).
- **DoD:** a hello agent using `serve()`+`build_runner()`+plugins runs end to end.
- **Size:** M.
- **✅ STATUS: DONE (2026-09-07).** `common/adk/{model,services,plugins,serve,tools,interrogation}.py`
  + `common/memory/factory.py` (build_bank lifted; `executor.py` re-exports) built on the copied v1
  engine. **379 passed, 13 skipped, ruff clean** — the copied engine suite is a faithful-copy proof,
  plus `tests/test_adk_foundation.py` (6 tests) exercises the foundation incl. the **InterrogationAgent
  driving the REAL refine engine** over a FakeBucket (pause→resume→finalize). Integration decisions
  proven: `to_a2a(...) -> Starlette` accepts a custom `runner=` + `agent_card=` (inject our
  DatabaseSessionService + plugins, keep skill parity); `DatabaseSessionService(db_engine=…)` reuses
  `common/db.py`'s engine directly; **InterrogationAgent reuses RefineSession's own bank persistence**
  (rehydrate-by-ctx) rather than re-porting loop state into ADK session state — lower risk, keeps
  B0–B6. `LessonRecallPlugin` is conservative (flag-gated no-op) pending A1 pack-ctx wiring.

### A1 — knowledge-gathering (KGA)
- **Goal:** KGA as an ADK agent graph (target graph in `02` §A.1).
- **Files [new]:** `knowledge_gathering/agent.py` [rewrite] (root agent: skills gather/refine/reads),
  `agents/gather_agent.py` (`GatherAgent(BaseAgent)` wrapping `run_gather`→`crawl` via
  `asyncio.to_thread`, yields progress+summary Events — I1/I5), `agents/refine_agent.py`
  (`RefineAgent` = `InterrogationAgent` with rounds business/technical/qa + QuestionGen/Understanding
  `LlmAgent`s + heuristic fallback), `adk_app.py`.
- **Reuse:** `loop/*`, `explore/*` verbatim; read tools from `common/adk/tools.py`.
- **Gate:** offline harness (RecordedAtlassian + FakeBucket as ADK InMemory services) yields the same
  nodes/tiers/gaps as v1 on `eval_rich`/`eval_thin`/`eval_bleed`; refine produces the same
  questions/understanding shape; **no hard-negative leak** on the bleed fixture (I2);
  multi-turn refine survives a simulated restart via `DatabaseSessionService`.
- **DoD:** live gather→refine→approve for a real ticket through the real MCP bridge == v1 output.
- **Size:** L.
- **◑ STATUS: offline gates DONE (2026-09-08).** Built `agents/gather_agent.py` (`GatherAgent`
  re-triggers v1's crawl verbatim), `agents/refine_agent.py` (`RefineAgent` = `InterrogationAgent`),
  `adk_agent.py` (`KgaRouter` — deterministic text dispatch mirroring v1's executor; reads run inline,
  gather/refine delegate to sub-agents), `adk_app.py` (`serve(root, agent_card=AGENT_CARD)` for skill
  parity). **`tests/test_adk_kga.py`: GatherAgent persists the byte-identical node set to v1** for
  `eval_rich`/`eval_thin` (parity), and the router drives gather→refine (pause/resume→finalize)→reads.
  **382 passed, 13 skipped, ruff clean.** Notes: v1's `agent.py`/executors are kept during transition
  (dropped when the shell is removed); the **explore-loop path (KGA_EXPLORE_LOOP, default OFF) + the
  LessonRecall injection are A1 follow-ups**. Remaining for full A1: swap to `DatabaseSessionService`
  live (A1-c) + deploy behind the bridge (A1-d) — the latter must ensure the pipeline `context_id`
  maps to a **stable ADK `session_id`** across the gather→refine A2A calls (the bridge sends it, or
  to_a2a derives it from `context_id`) — see §5.

### A2 — test-plan-definition (TPD)
- **Goal:** TPD as an ADK agent graph (target graph in `02` §A.2); reuse the `InterrogationAgent` base.
- **Files [new]:** `test_plan_definition/agent.py` [rewrite], `agents/define_agent.py`
  (`InterrogationAgent` with rounds methodology/scope/metrics + QuestionGen/Brief `LlmAgent`s),
  `agents/implement_agent.py` (`ImplementAgent(BaseAgent)` wrapping `implement_plan` via
  `asyncio.to_thread`; `ScenariosAgent` `LlmAgent` = the one default call; test-data+steps `LlmAgent`s
  **gated behind `detail`/`TPD_LLM_DETAIL`** — I3), `approve_plan` FunctionTool (deterministic),
  `adk_app.py`.
- **Reuse:** `define/*`, `implement/*`, `llm/*`, `render/*`, `pack.py` verbatim.
- **Gate:** define over `plan_*` fixtures → same brief/decisions; scope leak stays out (I2);
  `implement` default runs **exactly one** LLM call and stays within the Cloud Run timeout (I3);
  scenarios/steps/`.feature` byte-comparable to v1 for a fixture pack.
- **DoD:** live define→approve→implement→get_scenarios == v1.
- **Size:** M.
- **◑ STATUS: offline gates DONE (2026-09-08).** `agents/define_agent.py` (registers a **"plan"
  `SessionSpec`** so the shared `InterrogationAgent` drives TPD's `PlanSession` — one loop, two
  configs; `common` never imports TPD, I6), `agents/implement_agent.py` (`ImplementAgent` wraps
  `implement_plan` in `asyncio.to_thread`, **`TPD_LLM_DETAIL` 1-call default preserved** — I3),
  `adk_agent.py` (`TpdRouter`: reads → approve → define → implement, deterministic), `adk_app.py`
  (`serve(agent_card=AGENT_CARD)`). `InterrogationAgent` was generalized (SessionSpec registry) —
  KGA refine + TPD define now share one class; KGA tests stayed green. **`tests/test_adk_tpd.py`:
  define→approve→implement over the real `run-6f2a` pack completes (plan CONFIRMED, scenarios
  persisted), implement default is the deterministic heuristic path. 383 passed, 13 skipped, ruff
  clean.** Remaining for full A2: DB sessions live + deploy (A2-c), shared with A1-c/d.

### B — evaluator on `adk eval` (Plan B)
- **Goal:** rebuild the evaluator on ADK's native eval framework; the domain math becomes ADK custom
  metrics (full design in `03`).
- **Files [new]:** `test_evaluation/eval/evalsets/*.evalset.json` (from `golden/*` + `golden_plans/*`,
  domain fields in `custom` metadata), `eval/test_config.json` (thresholds incl.
  `hard_negative_leak==0`, `pqs_score`/`tps_score` mins), `eval/metrics/*.py` (custom metrics wrapping
  the unchanged `metrics/*` fns: `retrieval_overlap`, `entities_recall`, `fabrication_rubrics`,
  `coverage_matrix`, `oracle_strength`, `fault_class_coverage`, `placeholder_leak`, `pqs_score`,
  `tps_score`), `adk_app.py` (the runtime `evaluate_pack`/`evaluate_plan` MCP-facing agent, calling
  the *same* metric code).
- **Reuse:** `metrics/*`, `golden*`, `models.py`, `engine.py`, `plan_engine.py` verbatim.
- **Gate:** `adk eval` reproduces v1's PQS/TPS on the three fixtures (± rounding); leak gate fails a
  bleed case; native `tool_trajectory_avg_score` matches E0/T0; the semantic-rubric catalog *runs*
  via `rubric_based_final_response_quality_v1` (nightly, judge = Claude-via-LiteLlm, skips if unset).
- **DoD:** `google-adk` is on-path; one metric codebase shared by CI `adk eval` + the runtime MCP tool.
- **Size:** M.
- **◑ STATUS: core DONE (2026-09-08).** Built `test_evaluation/eval/`: `adk_metrics.py` (domain
  metrics as ADK **custom-metric functions** — the exact `(EvalMetric, actual, expected, scenario) ->
  EvaluationResult` contract, loadable by dotted `custom_function_path`; they wrap the **unchanged v1
  engine** so numbers reproduce by construction), `evalset.py` (golden JSON → ADK `EvalSet`/`EvalCase`/
  `Invocation`), `config.py` (`EvalMetric` criteria + thresholds; the leak gate = threshold 1.0).
  **`tests/test_adk_eval.py`: PQS & TPS reproduce the v1 engine THROUGH google-adk's `EvaluationResult`
  types; the hard-negative leak gate PASSES clean / FAILS on a forbidden node; golden→EvalSet
  round-trips. 388 passed, 13 skipped, ruff clean.** `google-adk` is now genuinely imported + on-path
  (was a pin only). Installed the eval extra (pandas). **Remaining (follow-ups):** run under the full
  `AgentEvaluator`/`adk eval` CLI over the real agents; wire native `tool_trajectory_avg_score` +
  the judged tier (`hallucinations_v1`, `rubric_based_final_response_quality_v1` — the v1 semantic-
  rubric catalog finally runs) with a judge model; re-point the runtime `evaluate_pack`/`evaluate_plan`
  MCP tools to share this code; remaining domain metrics (coverage/oracle/fault as standalone ADK
  metrics — today folded into the pqs/tps composites).

### D — deployment
- **Goal:** deploy the v2 agents on the unchanged Cloud Run sidecar topology.
- **Files:** copy `deployments/test-agent-v1/` → `deployments/test-agent-v2/` (own terraform state);
  edit the **agent container start command** → the `to_a2a` app (`uvicorn <pkg>.adk_app:app`, same
  `:8081`, same probes); **image name** split (`test-agent-v2`); `DatabaseSessionService` reuses the
  existing Cloud SQL env (repurpose the task-store env).
- **Gate:** parity smoke test through the deployed bridge; latency within the request timeout (I3).
- **DoD:** v2 reachable behind its bridge; v1 untouched; rollback = revert the one container start cmd.
- **Size:** M.

---

## 5. Session & state design (concrete)

- **`context_id` → ADK `session_id`.** One id across gather→refine→define→implement, as today.
- **Interrogation loop state** (pending rounds, deferred/carried Qs, answered set, insight ids, pass
  counter, `done`) lives in ADK **session `state`** (Option B), replacing v1's GCS `state.json` +
  `_sessions/*.json`. The pack is still recomputed each turn from the run-scoped GCS index (B0 — I2).
- **Pause/resume:** `InterrogationAgent` reads state → advances one round → if open questions, writes
  state + emits the rendered round as its response + ends the invocation. Next A2A turn = fresh
  invocation: read state, `ingest` the answer, advance. No LRO-in-Sequential (avoids R1).
- **Durability:** `DatabaseSessionService` subsumes the v1 A2A `DatabaseTaskStore` + the GCS state
  files into one store (see `01` §5).
- **Artifacts (optional):** register final `scenarios.md`/`.feature`/`plan-brief.md` with
  `GcsArtifactService` for the `adk web` UI; the GCS bank stays the authority.

## 6. Testing & CI strategy

- **Reuse the offline harness** (`tests/eval/harness*.py`: RecordedAtlassian + FakeBucket) as the
  ADK Runner's injected tools/`InMemorySessionService` — run the *real* graph, touch nothing external.
- **Equivalence suite:** for each fixture, assert v2 output == v1 (nodes/tiers/gaps; brief/decisions;
  scenarios/`.feature`). This is the primary "did the port regress?" gate.
- **Invariant gates** (§1) as explicit tests: leak==0 (I2), implement call-count==1 (I3), skill-parity
  (I4), disabled-thinking JSON parse (I5), no-cross-agent-import (I6), Vertex-off deterministic (I7).
- **Plan B is the judge:** `adk eval` PQS/TPS on v2 must match v1's numbers.

## 7. Sequencing, effort, rollback

```
M0 → A0(spike) → A.0(foundation) → A1(KGA) → A2(TPD) → B(evaluator) → D(deploy)
```
- KGA before TPD (A1 yields the reusable `InterrogationAgent` base A2 consumes). Evaluator last (it
  judges the migration). Deployment per-agent — 0..3 agents can be on ADK at any time.
- **Effort:** ~70% reuse (copy+wrap), ~30% new (`common/adk/`, agent graphs, state migration, evalsets).
- **Rollback:** per-agent — revert the one agent container's start command + image tag; v1, the bridge,
  the other agents, and all data are untouched. `VERTEX_*` unset forces the deterministic path (I7).
- **Full risk register:** `../../docs/adk-transform/04-roadmap-risks.md` (R1 HITL resume is the one to
  spike; R2 LiteLlm thinking/max_tokens; R3 blocking work on the event loop).

## 8. Definition of done

1. KGA + TPD served as ADK agent graphs via `to_a2a`, behind the unchanged bridge; MCP surface identical.
2. Equivalence suite green (v2 == v1 outputs on all fixtures); all seven invariant gates green.
3. `DatabaseSessionService` is the single durable session store (v1's task store + GCS state files retired).
4. Evaluator on `adk eval` with real `google-adk`; PQS/TPS reproduce v1; leak gate is a first-class fail.
5. `test-agent-v1` untouched and still deployable throughout; every `[verify @2.x]` ADK API resolved.

---

## 9. A0 spike findings — confirmed ADK facts (env: `google-adk 2.8.0`, python 3.12)

Established by running the A0 spike (since removed), not assumed. **The `>=1.22` pin resolves to 2.x — the
docs' `[verify @1.22]` markers should read `[verify @2.x]`, and the pin should become
`google-adk[db]>=2`.**

- **Decision:** RefineAgent/DefineAgent use **Option B** (custom `BaseAgent` + session-state
  checkpoint). Proven; avoids the LRO-in-Sequential resume bugs (R1) entirely.
- **`DatabaseSessionService` needs `google-adk[db]` + an async driver** — it calls
  `create_async_engine`, so `common/adk/services.py` must dial **`postgresql+asyncpg://…`** in prod
  (the same asyncpg `common/db.py` already uses); a plain `postgresql://`/`sqlite://` URL fails.
- **Checkpoint pattern:** persist loop state by yielding `Event(actions=EventActions(state_delta={…}))`
  — mutating `ctx.session.state` alone does not persist. Keep the agent **stateless** (no pydantic
  fields); all state lives in session state so any instance resumes any session.
- **Verified-on-2.8.0 APIs:** `BaseAgent._run_async_impl(self, ctx)` yielding `Event`;
  `EventActions(state_delta=…)`; `Runner.run_async(user_id=, session_id=, new_message=types.Content(…))`;
  `await session_service.{create,get}_session(app_name=, user_id=, session_id=)`.
- **Still to verify @2.x during A.0/B:** `to_a2a` import path + card generation; `LiteLlm` thinking/
  max_tokens kwargs; the eval-metric registry (`tool_trajectory_avg_score`, `hallucinations_v1`,
  `rubric_based_*`, custom metrics).
