"""Live JEV cascade calibration — pick `TPD_DECISION_CONF_MIN` from real data (rollout step 2).

Unlike the offline `tools/jev_experiment.py` (modeled, FakeDecisionProvider), this drives the REAL
`typesafe-sdk` JEV Score and the REAL LLM judge (`judge_once`) so it needs BOTH a JEV key and Vertex.

Method — the cascade's own contract is "trust JEV's fast Score only where it makes the SAME ship/no-ship
call the production LLM judge would." So we treat the LLM judge as the reference oracle:

  1. Build real, VARYING-quality suites from the golden plans (each golden seed × {full, drop1, half,
     one, mismatch}) so JEV's confidence has a real spread to be calibrated against.
  2. For each: JEV `score()` → (score, confidence) on the *identical* state the gate scores
     (`assured.loop.suite_state`); LLM `judge_once` (median-of-k, as production) → reference score.
  3. accept = score >= TPD_ASSURED_THRESHOLD (0.7). agree = (jev_accept == llm_accept).
  4. Sweep candidate τ_conf mirroring the gate (`loop._decision_gate`): the fast path fires ONLY on
     confident ACCEPTS (`jev_acc AND conf >= τ`) — a JEV reject never short-circuits. precision =
     correct-accept rate over the fired rows; take-rate = |fired|/N. Recommend the smallest τ whose
     precision >= --target (default 0.90). (Counting confident rejects here would inflate precision.)
  5. Also report the two J4 blockers directly: JEV's confidence on the LLM-ACCEPTED rows, and JEV-vs-LLM
     per-gate latency (what the fast path actually saves when it fires).

CEILING (ponytail): N is small (3 goldens × 5 variants = 15) and the "quality" spread is synthetic
(structural degradation), not human-graded — this is a calibration *procedure* + first data point, not a
final threshold. Widen the golden set / add real bad suites before trusting τ in production.

Run: PYTHONIOENCODING=utf-8 uv run --extra jev python tools/jev_calibrate.py [--target 0.9] [--samples 3]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import pathlib
import sys
import time

# --- env: load .env so BOTH TYPESAFE_API_KEY and VERTEX_* reach os.environ; turn JEV on --------------
_ENV = pathlib.Path(__file__).resolve().parent.parent / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.lstrip().startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())
os.environ["TPD_DECISION_BACKEND"] = "jev"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

ACCEPT_THRESHOLD = float(os.environ.get("TPD_ASSURED_THRESHOLD", "0.7"))
CONF_GRID = [round(0.20 + 0.05 * i, 2) for i in range(16)]  # 0.20 .. 0.95


def _variants(scenarios, other):
    """The five quality grades from one golden suite (real scenarios; `other` = a different seed's).

    `drop1` (full minus one scenario) is the near-accept borderline probe — the point most likely to
    straddle the accept line, so JEV/LLM can actually diverge there. Skipped for tiny suites where it
    would just duplicate `half`/`one`."""
    return {
        "full": list(scenarios),
        "drop1": scenarios[:-1] if len(scenarios) > 2 else [],
        "half": scenarios[: max(1, len(scenarios) // 2)],
        "one": scenarios[:1],
        "mismatch": list(other),  # scenarios that don't match this plan/pack → should grade low
    }


async def _llm_score(plan, scenarios, summary, model, samples: int) -> float | None:
    """Median-of-k `judge_once`, exactly the production reference (loop.py)."""
    from test_plan_definition.implement.assured.loop import judge_once

    scores = []
    for _ in range(samples):
        v = await judge_once(plan, scenarios, summary, model)
        if v is not None:
            scores.append(v.score())
    return sorted(scores)[len(scores) // 2] if scores else None


def _sweep(rows: list[dict], target: float) -> None:
    n = len(rows)
    print(f"\n{'τ_conf':>7}  {'take-rate':>10}  {'accept-prec':>15}  {'n_fired':>7}   (accept-only fast path)")
    print("  " + "-" * 46)
    best = None
    for tau in CONF_GRID:
        fast = [r for r in rows if r["jev_acc"] and r["conf"] >= tau]  # gate fires on ACCEPTS only
        prec = (sum(r["agree"] for r in fast) / len(fast)) if fast else float("nan")
        take = len(fast) / n if n else 0.0
        star = ""
        if fast and prec >= target and best is None:
            best, star = tau, "  <= recommended (smallest τ meeting target)"
        p = f"{prec:.2f}" if fast else "  n/a"
        print(f"{tau:>7.2f}  {take:>9.0%}  {p:>15}  {len(fast):>7}{star}")
    print()
    if best is None:
        print(f"NO τ on the grid reaches precision >= {target:.2f}; either JEV disagrees with the LLM "
              "judge too often on this set, or N is too small. Do NOT enable the fast path yet.")
    else:
        fast = [r for r in rows if r["jev_acc"] and r["conf"] >= best]
        print(f"RECOMMEND  TPD_DECISION_CONF_MIN={best}  "
              f"(fast-path precision {sum(r['agree'] for r in fast)/len(fast):.2f} "
              f"at {len(fast)/n:.0%} take-rate, target {target:.2f}).")


def _summary(rows: list[dict], samples: int) -> None:
    """J4's two open questions with real data: JEV's confidence on correct ACCEPTS, and JEV-vs-LLM latency."""
    import statistics as st

    accepts = [r for r in rows if r["llm_acc"]]
    print("Accept-side confidence (rows the LLM judge ACCEPTED — can the fast path capture the win?):")
    if accepts:
        confs = [r["conf"] for r in accepts]
        print(f"  n={len(accepts)}  conf min {min(confs):.2f} / mean {st.mean(confs):.2f} / max {max(confs):.2f}"
              f"  |  JEV also accepted {sum(r['jev_acc'] for r in accepts)}/{len(accepts)}")
    else:
        print("  none — no accept-side rows on this set (widen goldens with genuinely-good suites).")

    jev = [r["jev_ms"] for r in rows]
    llm = [r["llm_ms"] for r in rows if r["llm_ms"] is not None]
    print("\nLatency per gate (what the fast path saves when JEV is trusted):")
    print(f"  JEV score():             mean {st.mean(jev):7.0f} ms  (n={len(jev)})")
    if llm:
        print(f"  LLM judge median-of-{samples}:    mean {st.mean(llm):7.0f} ms  (n={len(llm)})")
        print(f"  => fast path saves ~{st.mean(llm) - st.mean(jev):.0f} ms per gate it takes.")
    print()


async def main() -> int:
    ap = argparse.ArgumentParser(description="Calibrate the JEV cascade confidence threshold on goldens.")
    ap.add_argument("--target", type=float, default=0.90, help="min fast-path precision to accept a τ")
    ap.add_argument("--samples", type=int, default=3, help="LLM judge samples per item (median)")
    args = ap.parse_args()

    from common.adk import agent_model
    from common.adk.providers import get_decision_provider
    from common.llm.vertex import vertex_config
    from common.testplan.pack import load_plan_pack
    from test_evaluation.golden import load_golden_plans
    from test_plan_definition.implement.assured.loop import suite_state
    from tests.eval.harness_tpd import run_plan_offline

    decision = get_decision_provider()
    if decision is None or not decision.is_configured():
        print("FATAL: JEV not configured (TYPESAFE_API_KEY missing). Nothing to calibrate.")
        return 2
    have_llm = bool(vertex_config())
    if not have_llm:
        print("WARN: Vertex not configured — no LLM oracle. Reporting the confidence DISTRIBUTION only "
              "(no agreement/precision, so no threshold recommendation).\n")
    model = agent_model(tier="fast") if have_llm else None

    cases = load_golden_plans()
    print(f"Building suites from {len(cases)} golden plan(s): {[c['seed'] for c in cases]}")
    traces = {}
    for c in cases:
        t = run_plan_offline(c["seed"], c["fixture"], depth=c.get("depth", 1))
        traces[c["seed"]] = (t, load_plan_pack(t.bank, t.ctx, seed=f"jira:{c['seed']}"))

    seeds = list(traces)
    rows: list[dict] = []
    print(f"\n{'item':>22}  {'jev_score':>9}  {'conf':>5}  {'llm':>5}  {'jev_acc':>7}  {'llm_acc':>7}  agree")
    print("  " + "-" * 74)
    for i, seed in enumerate(seeds):
        trace, pack = traces[seed]
        other = traces[seeds[(i + 1) % len(seeds)]][0].result.scenarios  # a different seed's suite
        for name, scns in _variants(trace.result.scenarios, other).items():
            if not scns:
                continue
            state = suite_state(pack, scns)
            _t = time.perf_counter()
            v = decision.score(
                state=state, levels=["low", "medium", "high"],
                instructions="Is this test suite good enough to ship for this plan? Grade its overall quality.")
            jev_ms = (time.perf_counter() - _t) * 1000.0
            jev_score, conf = float(v.value), float(v.confidence)
            jev_acc = jev_score >= ACCEPT_THRESHOLD
            _t = time.perf_counter()
            llm = await _llm_score(trace.plan, scns, pack.summary_text(), model, args.samples) if have_llm else None
            llm_ms = (time.perf_counter() - _t) * 1000.0 if have_llm else None
            llm_acc = (llm >= ACCEPT_THRESHOLD) if llm is not None else None
            agree = (jev_acc == llm_acc) if llm_acc is not None else None
            if agree is not None:
                rows.append({"conf": conf, "agree": int(agree), "jev_ms": jev_ms, "llm_ms": llm_ms,
                             "jev_acc": jev_acc, "llm_acc": llm_acc})
            item = f"{seed}/{name}"
            ls = f"{llm:.2f}" if llm is not None else " n/a"
            ag = "" if agree is None else ("YES" if agree else "no")
            print(f"{item:>22}  {jev_score:>9.2f}  {conf:>5.2f}  {ls:>5}  {jev_acc!s:>7}  {llm_acc!s:>7}  {ag}")

    if not have_llm:
        print("\n(confidence distribution shown in the table above; configure Vertex for a recommendation.)")
        return 0
    if not rows:
        print("\nNo LLM verdicts returned — cannot calibrate. Check Vertex creds / quota.")
        return 1
    _sweep(rows, args.target)
    _summary(rows, args.samples)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
