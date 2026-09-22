"""A/B latency harness — LUZ-158230, baseline vs turbo+fast, real Vertex, single process.

Turbo (TESTAGENT_TURBO) and the fast tier (VERTEX_MODEL_FAST) only touch the LLM stages
(refine/define/implement), so we gather ONCE (live Atlassian, no repo= => no codegraph build), then run
refine->define->implement for each arm on an isolated clone of the gathered bank — timing each stage and
capturing the scenario count + assured score. Reuses the offline test harness as the pipeline driver but
runs OUTSIDE pytest, so the `_offline_default_no_vertex` fixture does NOT apply => real Vertex.

Arms:
  baseline   — TESTAGENT_TURBO unset, VERTEX_MODEL_FAST unset (full model, full quality; Mode A is always on)
  turbo+fast — TESTAGENT_TURBO=1, VERTEX_MODEL_FAST=claude-haiku-4-5

Run (needs VERTEX_* + ATLASSIAN_* in env/.env):
    cd test-agent-v2 && python tools/ab_latency.py
Env knobs: AB_DEPTH (gather depth, default 2), AB_MODEL_FAST (default claude-haiku-4-5), AB_TICKET (default LUZ-158230).

NOTE: dev tool — imports the test harness on purpose (don't reinvent the pipeline driver).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]  # test-agent-v2/
for p in (_ROOT, _ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _clock():
    return time.monotonic()


def _set_env(turbo: bool, model_fast: str | None) -> None:
    """Set the arm's env; each gate reads os.environ fresh so this is enough (single process)."""
    if turbo:
        os.environ["TESTAGENT_TURBO"] = "1"
    else:
        os.environ.pop("TESTAGENT_TURBO", None)
    if model_fast:
        os.environ["VERTEX_MODEL_FAST"] = model_fast
    else:
        os.environ.pop("VERTEX_MODEL_FAST", None)


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv()
    missing = [k for k in ("VERTEX_PROJECT", "VERTEX_LOCATION", "VERTEX_MODEL", "ATLASSIAN_BASE_URL",
                           "ATLASSIAN_EMAIL", "ATLASSIAN_API_TOKEN") if not os.environ.get(k)]
    if missing:
        print(f"ERROR: missing env: {missing}", flush=True)
        return 2

    from common.atlassian.factory import build_client
    from common.memory import MemoryBank
    from test_evaluation.benchmark import compute_benchmark
    from tests.conftest import FakeBucket
    from tests.eval.harness import run_gather_offline, run_refine_offline
    from tests.eval.harness_tpd import run_define_offline, run_implement_offline

    ticket = os.environ.get("AB_TICKET", "LUZ-158230")
    depth = int(os.environ.get("AB_DEPTH", "2"))
    model_fast = os.environ.get("AB_MODEL_FAST", "claude-haiku-4-5")
    ctx = f"ab-{ticket.lower()}"

    # 1) Gather ONCE (live). No repo= => skip the codegraph build (the fragile/slow part). Turbo/fast
    #    don't affect gather, so it's shared across arms. Keep the base bucket to clone per arm.
    base = FakeBucket()
    _set_env(turbo=False, model_fast=None)  # gather uses no LLM planners by default (explore off)
    t = _clock()
    tr = run_gather_offline(ticket, client=build_client(), bank=MemoryBank(base),
                            text=f"gather {ticket} depth {depth}", context_id=ctx)
    gather_s = _clock() - t
    print(f"[gather] {gather_s:.1f}s, reply={len(tr.reply)} chars, blobs={len(base.store)}", flush=True)

    def clone() -> MemoryBank:
        b = FakeBucket()
        b.store = dict(base.store)
        b.gens = dict(base.gens)
        return MemoryBank(b)

    # arms = (name, turbo, model_fast): the 2x2 turbo/fast decomposition.
    arms = [("baseline", False, None), ("fast-only", False, model_fast),
            ("turbo-only", True, None), ("turbo+fast", True, model_fast)]
    results = []
    for name, turbo, mf in arms:
        _set_env(turbo=turbo, model_fast=mf)
        bank = clone()
        timings = {}
        for stage, fn in (("refine", lambda bank=bank: run_refine_offline(bank, ctx, seed=f"jira:{ticket}")),
                          ("define", lambda bank=bank: run_define_offline(bank, ctx, seed=f"jira:{ticket}")),
                          ("implement", lambda bank=bank: run_implement_offline(bank, ctx))):
            t = _clock()
            out = fn()
            timings[stage] = round(_clock() - t, 1)
            impl = out if stage == "implement" else None
        bm = compute_benchmark(bank, ctx)
        q = getattr(impl, "quality", None)
        rec = {
            "arm": name, "turbo": turbo, "model_fast": mf,
            "timings_s": timings, "llm_total_s": round(sum(timings.values()), 1),
            "scenarios": len(getattr(impl, "scenarios", []) or []),
            "assured_score": getattr(q, "final_score", None),
            "pqs": bm.pqs, "tps": bm.tps,
        }
        results.append(rec)
        print(f"[{name}] refine {timings['refine']}s / define {timings['define']}s / "
              f"implement {timings['implement']}s | LLM total {rec['llm_total_s']}s | "
              f"scenarios={rec['scenarios']} score={rec['assured_score']} pqs={bm.pqs} tps={bm.tps}",
              flush=True)

    base = results[0]["llm_total_s"] or 0.1
    for r in results:  # each arm's speed + quality relative to baseline
        r["speedup_vs_baseline_x"] = round(base / max(r["llm_total_s"], 0.1), 2)
    summary = {"ticket": ticket, "ctx": ctx, "depth": depth, "model_fast": model_fast,
               "gather_s": round(gather_s, 1), "arms": results}
    out_path = _ROOT / "ab_latency_results.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\n=== SUMMARY (vs baseline) ===", flush=True)
    for r in results:
        print(f"  {r['arm']:<12} {r['llm_total_s']:>6.0f}s  {r['speedup_vs_baseline_x']}x  "
              f"pqs={r['pqs']} tps={r['tps']} assured={r['assured_score']} scenarios={r['scenarios']}",
              flush=True)
    print(f"wrote {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
