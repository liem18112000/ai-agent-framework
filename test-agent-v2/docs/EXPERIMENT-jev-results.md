# Experiment results — JEV DecisionProvider cascade

*2026-09-21 · branch `experiment/jev-decision-provider` · companion to [`RESEARCH-jev-in-test-agent-v2.md`](RESEARCH-jev-in-test-agent-v2.md).*

## What was actually tested (and the honest limit)

There is **no real JEV endpoint** (early-access); `JevProvider` is a guarded stub that raises if called. So this is **not** a live-JEV benchmark. It measures the thing that *is* real today: the **cascade plumbing and the LLM-judge-call reduction**, by driving the real code paths (`run_assured_scenarios`, `build_semantic_judge`) with `FakeDecisionProvider` as a stand-in JEV and the offline fake model as a stand-in LLM. **Call counts are measured; latency/cost are modeled** (vendor per-call figures × measured call counts).

Harness: `tools/jev_experiment.py` (throwaway, offline). Tests still green: `pytest -k "decision or judge or assured"` → **63 passed, 6 skipped**.

## Experiment A — assured loop, per `implement_plan` run
Production default `TPD_JUDGE_SAMPLES=3`; fake judge scores 0.9.

| config | LLM judge calls | accepted? | rounds |
|---|---|---|---|
| A1 baseline (backend OFF) | **3** | yes | 1 |
| A2 JEV accept-fast (score 0.92, conf 0.9) | **0** | yes | 1 |
| A3 JEV fallback (score 0.92, conf 0.4) | **3** | yes | 1 |

**LLM-judge-calls avoided = 3 → 0 per run** on the confident-and-above-bar case (= `TPD_JUDGE_SAMPLES` × rounds; scales linearly). On the low-confidence tail (A3) the cascade falls back to the identical LLM path (+1 wasted JEV call) — behaviour byte-identical to baseline on the LLM side.

## Experiment B — TEV `build_semantic_judge`, per 100 yes/no judgements

| config | LLM `complete` calls | result correct vs P(true)≥0.5 |
|---|---|---|
| B1 baseline (OFF) | **100** | — |
| B2 JEV noul, P=0.8 | **0** | ✓ all True |
| B3 JEV noul, P=0.2 | **0** | ✓ all False |

**LLM-calls avoided = 100 per 100 judgements (1:1)**, bool matches the calibrated probability both directions.

## Deploy-safety smoke — `main.build_app("test_plan_definition")`

| config | app boots? | `get_decision_provider()` | `is_configured()` |
|---|---|---|---|
| `TPD_DECISION_BACKEND` unset | ✅ | `None` | False → LLM |
| `TPD_DECISION_BACKEND=jev`, no key | ✅ | `JevProvider` | **False** → LLM, stub never reached |

The change is **deploy-safe**: gated OFF by default, and even mis-set to `jev` without a key it boots and routes to the LLM (the raising stub is never reached because every caller checks `is_configured()` first).

## Modeled latency / cost (vendor figures × measured counts — NOT measured wall-clock)
Vendor claims (TypeSafe's own, directional): JEV ~70–500 ms (point 150 ms), `$0.042/M` in, output free; LLM ~3–329 s, `$0.20–10/M` in + paid output. Offline prompt sizes: judge ~691 in-tok, JEV state ~159 in-tok.

- **Assured accept-fast (3 LLM → 1 JEV):** latency saved ≈ **8.85 s/run** (point), range **8.85 s … ~987 s/run** across the vendor LLM band; input-token cost saved ≈ **$0.0004 … $0.021/run** (LLM output cost extra, unmodeled).
- **TEV (100 LLM → 0):** ≈ 100 × per-call LLM cost/latency saved; JEV cost $0 in this run.

## Verdict
Plumbing works, is deploy-safe, and delivers the designed call-reduction (assured judge 3→0, TEV judge 1:1→0) on the confident path with LLM fallback on the tail. The **latency/cost magnitudes are unproven** — they ride entirely on vendor claims the research doc already flags as unverified (and possibly below a frontier LLM judge on raw accuracy). **Next real step: benchmark calibration and true latency against our TEV golden sets once JEV exposes an endpoint.** Until then: keep gated OFF.

## Caveats
- No real JEV, no real LLM offline → only call-counts are measured; latency/$ are modeled.
- Baseline uses production `TPD_JUDGE_SAMPLES=3` (pytest conftest forces 1); avoided-count scales with that env.
- Token cost grounded in the offline `LUZ-158390` fixture pack at ~4 chars/token; real tickets differ.
- Accuracy/calibration of a *real* JEV is untested here — the fake is assumed-correct by construction.
