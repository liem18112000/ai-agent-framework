"""Plan B — the evaluator on ADK's eval framework, offline.

Proves: (1) domain metrics run through google-adk's custom-metric contract and RETURN google-adk
EvaluationResult objects; (2) PQS/TPS reproduce the v1 engine numbers (same math, now ADK-wrapped);
(3) the hard-negative leak gate PASSES on a clean pack and FAILS when a golden must-not-retrieve node
is actually present; (4) golden JSON → ADK EvalSet round-trips.
"""

from __future__ import annotations

from google.adk.evaluation.eval_metrics import EvalMetric, EvalStatus
from google.adk.evaluation.eval_set import EvalSet
from google.adk.evaluation.evaluator import EvaluationResult

from test_evaluation.engine import evaluate_pack
from test_evaluation.eval import adk_metrics
from test_evaluation.eval.evalset import eval_case_for, pack_eval_set, plan_eval_set
from test_evaluation.executor.base import golden_for
from test_evaluation.plan_engine import evaluate_plan
from tests.eval.harness import recorded_client, run_gather_offline
from tests.eval.harness_tpd import run_plan_offline


def _run(metric_fn, seed, threshold) -> EvaluationResult:
    conv = eval_case_for(seed).conversation
    return metric_fn(EvalMetric(metric_name=metric_fn.__name__, threshold=threshold), conv)


def test_pqs_reproduces_via_adk_custom_metric():
    seed = "LUZ-501"
    trace = run_gather_offline(seed, client=recorded_client("eval_rich"), context_id=seed)
    adk_metrics.set_bank(trace.bank)

    v1 = evaluate_pack(trace.bank, seed, golden_for(seed))         # v1 engine
    res = _run(adk_metrics.pqs_score, seed, 0.70)                  # ADK custom metric

    assert isinstance(res, EvaluationResult)                       # google-adk type on-path
    assert res.overall_score == v1.pqs                        # reproduces exactly
    assert res.per_invocation_results[0].score == v1.pqs


def test_leak_gate_passes_on_clean_pack():
    seed = "LUZ-501"
    trace = run_gather_offline(seed, client=recorded_client("eval_rich"), context_id=seed)
    adk_metrics.set_bank(trace.bank)
    res = _run(adk_metrics.hard_negative_leak, seed, 1.0)
    assert res.overall_eval_status == EvalStatus.PASSED           # no hard-negative leaked


def test_leak_gate_fails_when_forbidden_node_present(monkeypatch):
    """Force a leak: a golden must-not-retrieve = a node that IS in the pack → metric FAILS."""
    from test_evaluation.models import EvalCase as DomainEvalCase
    seed = "LUZ-501"
    trace = run_gather_offline(seed, client=recorded_client("eval_rich"), context_id=seed)
    adk_metrics.set_bank(trace.bank)
    leaky = DomainEvalCase.from_dict({"seed": seed, "must_not_retrieve_ids": [f"jira:{seed}"]})
    monkeypatch.setattr("test_evaluation.eval.adk_metrics.golden_for", lambda _c: leaky)
    res = _run(adk_metrics.hard_negative_leak, seed, 1.0)
    assert res.overall_eval_status == EvalStatus.FAILED           # the gate catches the leak


def test_tps_reproduces_via_adk_custom_metric():
    seed = "LUZ-501"
    trace = run_plan_offline(seed, "eval_rich", ctx=seed)
    adk_metrics.set_bank(trace.bank)

    res = _run(adk_metrics.tps_score, seed, 0.70)
    assert isinstance(res, EvaluationResult)
    # the metric uses golden_plan_for(seed) internally; compare against a matched-case v1 run
    from test_evaluation.executor.base import golden_plan_for
    v1_matched = evaluate_plan(trace.bank, seed, golden_plan_for(seed))
    assert res.overall_score == v1_matched.tps


def test_golden_becomes_adk_evalset():
    ps = pack_eval_set()
    assert isinstance(ps, EvalSet) and len(ps.eval_cases) >= 3    # eval_rich/thin/bleed
    assert plan_eval_set().eval_cases                            # plan_rich/thin/bleed
    # the seed rides in the invocation's user_content, recoverable by the metric
    inv = ps.eval_cases[0].conversation[0]
    assert inv.user_content.parts[0].text == ps.eval_cases[0].eval_id
