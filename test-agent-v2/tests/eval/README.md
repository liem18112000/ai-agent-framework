# KGA evaluation — tests

Scores the Testing Agent's **pack quality** — the measurement layer from
[`docs/RESEARCH-kga-evaluation-adk-ragas.md`](../../docs/RESEARCH-kga-evaluation-adk-ragas.md).

The engine is a **first-class agent**: [`src/test_evaluation/`](../../src/test_evaluation/) (metrics,
scoring engine, golden spec, A2A executor + MCP bridge). **This directory holds only the tests** plus
the offline **harness** that drives the *other* agents (KGA gather/refine) in-process — that harness
imports `knowledge_gathering`, so it stays test-side to keep `test_evaluation` free of cross-agent deps.

## Two tiers

| File | Phase | Cost | Gate |
|---|---|---|---|
| `test_metrics.py` | KGA metric math | none | PR-required |
| `test_eval_deterministic.py` | **E0** trajectory · **E1** node-overlap retrieval | none (no LLM/net) | PR-required |
| `test_engine.py` | the pack `evaluate_pack` engine + A2A executor | none | PR-required |
| `test_eval_judged.py` | **E2** RAGAS · **E3** entity/noise/topic · **E4** PQS/rubrics/history | E2 needs LLM | nightly / `eval:` |
| `test_eval_tpd_metrics.py` | TPD metric math (coverage/oracle/placeholder/gherkin/mutation/tps) | none | PR-required |
| `test_eval_tpd_deterministic.py` | **T0** trajectory · **T1** scope + coverage + placeholder | none (no LLM/net) | PR-required |
| `test_plan_engine.py` | the plan `evaluate_plan` engine + A2A executor | none | PR-required |
| `test_eval_tpd_judged.py` | **T2** RAGAS brief · **T3** gherkin/oracle · **T4** TPS/fault | T2 needs LLM | nightly / `eval:` |

The RAGAS tests (E2/T2) **skip** unless the `eval` extra is installed; everything else is deterministic.

**Two agents scored, one eval agent.** `evaluate_pack` scores the KGA *pack* (E-phases); `evaluate_plan`
scores the TPD *plan + suite* (T-phases). Both engines live in `src/test_evaluation/` and read the
persisted artifacts from the shared bank as dicts (never importing the scored agent). The TPD harness
(`harness_tpd.py`) drives the real `gather → refine → define → implement` in-process, reusing the KGA
`harness.py` to build the pack first.

```bash
# PR gate (seconds, deterministic)
pytest tests/eval/test_metrics.py tests/eval/test_eval_deterministic.py tests/eval/test_engine.py

# full judged tier (installs the LLM judge)
pip install -e '.[eval]'   &&  pytest tests/eval
```

## Layout

**Engine (shipped) — `src/test_evaluation/`:** `metrics/` (trajectory, node_overlap, entities, noise,
topic, ragas_judge, pqs, rubrics, history), `engine.py` (`evaluate_pack(bank, ctx, case)` scoring a
persisted pack), `golden.py` + `golden/*.json` (the EvalCases), `models.py`, plus the agent surface
(`agent.py`, `executor/`, `server.py`, `bridge/`).

**Tests (here) — `tests/eval/`:** `harness.py` (`run_gather_offline` / `run_refine_offline` + `RunTrace`
+ `RecordedAtlassianClient`), `fixtures/atlassian/*.json` (recorded Jira/Confluence responses), and the
test files above.

## Adding a seed

1. Record `fixtures/atlassian/<name>.json` (real: dump `build_client()` responses; synthetic: follow
   the Jira-issue shape in the existing fixtures).
2. Author `src/test_evaluation/golden/<name>.json`. Set thresholds to the **observed** gather (run the
   harness once, read `RunTrace.node_ids` / `.tiers`) — don't guess.

The three shipped seeds cover the shapes that break the KGA: `eval_rich` (happy path), `eval_bleed`
(hard-negative must not leak), `eval_thin` (0-links container → B1 parent-climb recovers the epic).
The §7 target is 8–15 seeds recorded against live Atlassian.
