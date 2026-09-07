# 03 · Plan B — the evaluator, "same or better" on ADK's eval framework

*The exception.* `test-evaluation` scores the other two agents; ADK ships a **first-class evaluation
framework** for exactly that. So instead of porting it "the same way" as KGA/TPD (agent-runtime
primitives), we rebuild it on **`adk eval`** — which is the "better method" the instruction invites,
and finally makes the ADK references in the code real instead of aspirational.

**Where this is built:** the ADK evaluator + evalsets + custom metrics live in **`test-agent-v2/`**
(the `metrics/*` math is lifted from `test-agent-v1/src/test_evaluation/`). See the README's
*Paths & versions*.

---

## B.0 — Why a different plan

Today the evaluator is a **hand-rolled reimplementation of ADK's own eval metrics** ([`00` §3]):
`trajectory.py` reimplements `tool_trajectory_avg_score`; `ragas_judge.py` reimplements
`hallucinations_v1`-intent via RAGAS; `rubrics.py` names `rubric_based_*` but the semantic rubrics are
**declarative only — never called**. And `google-adk` is a pin that nothing imports.

So the transfer here is not "wrap it in a workflow agent." It is: **adopt the native harness, keep
the domain metrics as ADK custom metrics, and turn the reimplementations into real ADK calls.**

## B.1 — The three metric classes and where each lands

| Class | Today | → ADK |
|-------|-------|-------|
| **Trajectory** — did the agent call the right tools/skills in order? (`trajectory.py`) | hand-rolled exact/in_order/any_order | **native `tool_trajectory_avg_score`** with a threshold in `test_config.json` (drop the reimpl) |
| **Generation quality** — is the understanding/brief faithful & on-topic? (`ragas_judge.py`, RAGAS faithfulness/relevancy) | RAGAS, nightly only, never in the composite | **native `hallucinations_v1`** (unsupported-claim detection) + **`final_response_match_v2`** (LLM-judged answer match) — judge model = Claude-via-LiteLlm or Gemini |
| **Semantic rubrics** — "names the AC", "declares gaps honestly" (`rubrics.py::SEMANTIC_RUBRICS`) | catalog only, **never runs** | **native `rubric_based_final_response_quality_v1`** — the catalog finally executes (a real *upgrade*, not a port) |
| **Domain-specific** — the leak gate, coverage matrix, oracle strength, fault-class, entity recall, PQS/TPS composites | deterministic, in `metrics/*` | **ADK custom metrics** (see B.3) — kept verbatim, run *inside* the ADK harness |

**"Same":** the golden ground-truth, the deterministic domain math, and the PQS/TPS composites are
preserved exactly. **"Better":** trajectory + generation quality become native ADK metrics with a
maintained judge; the semantic-rubric catalog actually runs; results flow through `adk eval`'s
runner/UI/history; real `google-adk` on-path.

## B.2 — Golden sets → ADK evalsets

- `golden/{eval_rich,eval_thin,eval_bleed}.json` and `golden_plans/{plan_*}.json` → **ADK
  `*.evalset.json`** files (`EvalSet` → `EvalCase` → invocations with `user_content` + expected
  `intermediate_data` tool-trajectory + `final_response` reference).
- The domain fields that ADK's schema has no slot for — `relevant_node_ids`, `must_not_retrieve_ids`,
  `must_not_scope_ids`, `behaviours`/`expected_partitions`, `pass_criteria`, `key_entities`,
  `min_recall`/`min_precision` — travel in each EvalCase's **`custom`/metadata** field and are read by
  the custom metrics (B.3). Nothing is lost.
- Per-metric thresholds move into **`test_config.json`** (`criteria`): e.g.
  `tool_trajectory_avg_score ≥ 1.0`, `hallucinations_v1 ≥ …`, plus custom
  `pqs_score ≥ …`, `tps_score ≥ …`, `hard_negative_leak == 0`.
- The **hard-negative leak gate** — today an offline `assert s.leaked == []` — becomes a **custom
  metric with threshold 0** (`hard_negative_leak`), so it is a first-class pass/fail in every
  `adk eval` run, not a bespoke assertion buried in a pytest.

## B.3 — Domain metrics as ADK custom metrics

ADK's eval framework is extensible: register custom metric evaluators (an `Evaluator` subclass /
metric-registry entry) that ADK invokes per EvalCase alongside the built-ins. Wrap the existing,
unchanged functions:

| Custom metric | Wraps (unchanged) | Feeds |
|---------------|-------------------|-------|
| `retrieval_overlap` (precision/recall/**leaked**) | `metrics/node_overlap.py::retrieval_scores` | PQS ctx_precision/recall; TPS scope; the leak gate |
| `entities_recall` | `metrics/entities.py` | PQS relevancy |
| `fabrication_rubrics` (cites-only-real-ids, no-invented-urls) | `metrics/rubrics.py` deterministic pair | PQS faithfulness; TPS brief_groundedness |
| `coverage_matrix` (AC-recall × matrix-completeness, traceability) | `metrics/coverage.py` | TPS coverage |
| `oracle_strength` | `metrics/oracle.py` | TPS oracle_strength |
| `fault_class_coverage` | `metrics/mutation.py` | TPS fault_detection |
| `placeholder_leak` | `metrics/placeholders.py` | reported (as today) |
| `pqs_score` / `tps_score` | `metrics/pqs.py` / `tps.py` | **the composites** (weighted mean of 5 components) |

The composites still assemble their 5 components — but now `trajectory` comes from ADK's native
`tool_trajectory_avg_score` (instead of the runtime-neutral 1.0), and the generation-quality
component can optionally be sourced from `hallucinations_v1` instead of the deterministic fabrication
rubrics (or keep both — deterministic as the gate, judged as a richer signal). **This closes the gap
noted in [`00` §3]** where the judged signals never reached the composite.

## B.4 — The "app under test" for `adk eval`

`adk eval` runs an **agent** against an evalset. Two viable shapes:

- **Recommended — evaluate the real KGA/TPD ADK agents (Plan A output) end-to-end.** Point `adk eval`
  at the KGA/TPD agents running against the **offline fixtures** (`RecordedAtlassianClient` +
  `FakeBucket` from `tests/eval/harness*.py`, reused as the agents' injected tools/services). This is
  strictly better than today: the *actual* agent trajectory is measured, not a re-driven copy.
- **Bridge shim** for the domain metrics: because the custom metrics score *persisted artifacts* (the
  pack/plan the agent wrote to the bank), the evalset's EvalCase runs the agent, then the custom
  metric reads the bank by `context_id` (== `session_id`) — the same path `engine.py`/`plan_engine.py`
  use today. No cross-agent import; the contract stays "read dicts from the bank."

The runtime MCP tools `evaluate_pack`/`evaluate_plan` remain available (a thin A2A agent) for
**on-demand, in-pipeline** scoring during a live `test` run — they call the *same* custom-metric
implementations now shared with the harness. So there is **one** metric codebase, two entry points
(CI `adk eval` + live MCP tool).

## B.5 — Test tiers under ADK

| Tier | Runs | Metrics | google-adk / judge |
|------|------|---------|--------------------|
| **PR gate (deterministic)** | every PR, no network/LLM | trajectory (native, exact) + all custom domain metrics incl. `hard_negative_leak==0`, `pqs_score`/`tps_score` | ADK harness, **no judge model** |
| **Nightly (judged)** | nightly / `eval:` label | + `hallucinations_v1`, `final_response_match_v2`, `rubric_based_final_response_quality_v1` | judge = Claude-via-LiteLlm (or Gemini); skips cleanly if unconfigured, mirroring today's `ragas_judge.available()` gate |

`history.py`'s JSONL trend + regression band is subsumed by ADK's eval-result store / `adk web` eval
history — keep the JSONL as a portable export if the team wants CI-diffable numbers.

## B.6 — Milestones

| ID | Milestone | Gate |
|----|-----------|------|
| B-a | Convert golden JSON → `*.evalset.json` + `test_config.json`; domain fields in `custom` metadata | round-trips: every golden case loads as an EvalCase with its ground-truth intact |
| B-b | Register the deterministic domain custom metrics (B.3) wrapping the unchanged `metrics/*` fns; `pqs_score`/`tps_score`/`hard_negative_leak` computed by ADK | `adk eval` on the three fixtures reproduces today's PQS/TPS numbers ± rounding; leak gate fails a bleed case |
| B-c | Native `tool_trajectory_avg_score` replaces `trajectory.py`; trajectory feeds the composites | trajectory pass/fail matches E0/T0 today |
| B-d | Nightly judged tier: `hallucinations_v1` + `rubric_based_final_response_quality_v1` (the catalog runs) + `final_response_match_v2`, judge via LiteLlm | judged tier runs when judge configured, skips otherwise |
| B-e | Runtime `evaluate_pack`/`evaluate_plan` re-pointed to the shared custom-metric code; deploy evaluator agent (via `to_a2a`, like Plan A) | live `evaluate_pack(ctx)` == pre-migration report for a real run |

## B.7 — Acceptance criteria for "Plan B done"

1. `adk eval` is the PR gate and the nightly judged tier; `google-adk` is actually imported and on-path.
2. PQS/TPS composites reproduce today's numbers on the three fixtures (± rounding); the hard-negative
   leak gate is a first-class `adk eval` failure (threshold 0), not a bespoke assertion.
3. The semantic-rubric catalog (`names_the_ac`, `declares_gaps_honestly`) **runs** via
   `rubric_based_final_response_quality_v1` — no longer dead code.
4. One metric codebase; the runtime MCP tools and the CI harness share it.
5. Trajectory + generation-quality signals now reach the composite (the [`00` §3] gap is closed).

## B.8 — Honest caveats

- **Judge portability**: ADK's judged metrics were built Gemini-first; running the judge as
  Claude-via-LiteLlm needs a validation pass (prompt/rubric behavior may differ). Keep the
  deterministic gate authoritative; treat judged scores as advisory until calibrated.
- **Evalset schema drift**: ADK's evalset/`test_config` schema evolves across 1.x — pin `google-adk`
  and snapshot the schema when B-a lands. [verify @1.22]
- **Custom-metric API surface**: the registry/`Evaluator` extension point is less documented than the
  built-ins; B-b should start with a one-metric spike (`hard_negative_leak`) before wrapping all eight.
