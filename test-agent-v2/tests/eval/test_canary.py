"""Canary tier (calibration) — a deliberately-bad case MUST score low and fire its leak gate.

These guard the METRIC, not the agent: if a canary ever scores above its ceiling (or its hard-negative
gate stops firing), the scorer is broken. Canaries live under golden/canary/ + golden_plans/canary/ so
the normal golden-pass gate and the ADK evalset never pick them up. See the RESEARCH docs' calibration §.
"""

from __future__ import annotations

import pytest

from test_evaluation.engine import evaluate_pack, evaluate_plan
from test_evaluation.golden import load_canaries, load_canary_plans
from test_evaluation.models import EvalCase, PlanEvalCase
from tests.eval.harness import recorded_client, run_gather_offline, run_refine_offline
from tests.eval.harness_tpd import run_plan_offline

_PACK = load_canaries()
_PLAN = load_canary_plans()


@pytest.mark.parametrize("d", _PACK, ids=[c["seed"] for c in _PACK])
def test_pack_canary_scores_low(d):
    case = EvalCase.from_dict(d)
    ctx = case.seed
    t = run_gather_offline(case.seed, client=recorded_client(case.fixture),
                           text=f"gather {case.seed} depth 1", context_id=ctx)
    run_refine_offline(t.bank, ctx, seed=f"jira:{case.seed}")
    r = evaluate_pack(t.bank, ctx, case)
    assert r.retrieval.leaked, f"{case.seed}: canary leak gate did not fire (metric broken)"
    assert r.pqs <= case.max_score, \
        f"{case.seed}: canary PQS {r.pqs} > ceiling {case.max_score} — the metric is broken, not the agent"


@pytest.mark.parametrize("d", _PLAN, ids=[c["seed"] for c in _PLAN])
def test_plan_canary_scores_low(d):
    case = PlanEvalCase.from_dict(d)
    t = run_plan_offline(case.seed, case.fixture)
    r = evaluate_plan(t.bank, t.ctx, case)
    assert r.scope.leaked, f"{case.seed}: canary scope-leak gate did not fire (metric broken)"
    assert r.tps <= case.max_score, \
        f"{case.seed}: canary TPS {r.tps} > ceiling {case.max_score} — the metric is broken, not the agent"
