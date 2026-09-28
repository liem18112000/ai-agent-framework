"""Plan B — the evaluator on ADK's eval framework, offline."""

from __future__ import annotations

from google.adk.evaluation.eval_metrics import EvalMetric, EvalStatus
from google.adk.evaluation.eval_set import EvalSet
from google.adk.evaluation.evaluator import EvaluationResult

from test_evaluation.engine import evaluate_pack, evaluate_plan
from test_evaluation.eval import adk_metrics
from test_evaluation.eval.evalset import eval_case_for, pack_eval_set, plan_eval_set
from test_evaluation.golden import golden_for
from tests.eval.harness import recorded_client, run_gather_offline
from tests.eval.harness_tpd import run_plan_offline


def _run(metric_fn, seed, threshold) -> EvaluationResult:
    conv = eval_case_for(seed).conversation
    return metric_fn(EvalMetric(metric_name=metric_fn.__name__, threshold=threshold), conv)


def test_pqs_reproduces_via_adk_custom_metric():
    seed = "LUZ-501"
    trace = run_gather_offline(seed, client=recorded_client("eval_rich"), context_id=seed)
    adk_metrics.set_bank(trace.bank)

    v1 = evaluate_pack(trace.bank, seed, golden_for(seed))
    res = _run(adk_metrics.pqs_score, seed, 0.70)

    assert isinstance(res, EvaluationResult)
    assert res.overall_score == v1.pqs
    assert res.per_invocation_results[0].score == v1.pqs


def test_leak_gate_passes_on_clean_pack():
    seed = "LUZ-501"
    trace = run_gather_offline(seed, client=recorded_client("eval_rich"), context_id=seed)
    adk_metrics.set_bank(trace.bank)
    res = _run(adk_metrics.hard_negative_leak, seed, 1.0)
    assert res.overall_eval_status == EvalStatus.PASSED


def test_leak_gate_fails_when_forbidden_node_present(monkeypatch):
    """Force a leak: a golden must-not-retrieve = a node that IS in the pack → metric FAILS."""
    from test_evaluation.models import EvalCase as DomainEvalCase
    seed = "LUZ-501"
    trace = run_gather_offline(seed, client=recorded_client("eval_rich"), context_id=seed)
    adk_metrics.set_bank(trace.bank)
    leaky = DomainEvalCase.from_dict({"seed": seed, "must_not_retrieve_ids": [f"jira:{seed}"]})
    monkeypatch.setattr("test_evaluation.eval.adk_metrics.golden_for", lambda _c: leaky)
    res = _run(adk_metrics.hard_negative_leak, seed, 1.0)
    assert res.overall_eval_status == EvalStatus.FAILED


def test_tps_reproduces_via_adk_custom_metric():
    seed = "LUZ-501"
    trace = run_plan_offline(seed, "eval_rich", ctx=seed)
    adk_metrics.set_bank(trace.bank)

    res = _run(adk_metrics.tps_score, seed, 0.70)
    assert isinstance(res, EvaluationResult)
    from test_evaluation.golden import golden_plan_for
    v1_matched = evaluate_plan(trace.bank, seed, golden_plan_for(seed))
    assert res.overall_score == v1_matched.tps


def test_golden_becomes_adk_evalset():
    ps = pack_eval_set()
    assert isinstance(ps, EvalSet) and len(ps.eval_cases) >= 3
    assert plan_eval_set().eval_cases
    inv = ps.eval_cases[0].conversation[0]
    assert inv.user_content.parts[0].text == ps.eval_cases[0].eval_id


# --- V4: the default scorer stays deterministic + LLM-free (the product property) ---------------

def test_default_scorer_makes_zero_llm_calls(monkeypatch):
    """The load-bearing gate (I1): `evaluate_pack`/`evaluate_plan` — the live A2A path — make ZERO
    model calls. Spy every LLM seam; the judged tier is separate and opt-in, never on this path."""
    seed = "LUZ-501"
    trace = run_gather_offline(seed, client=recorded_client("eval_rich"), context_id=seed)
    plan_trace = run_plan_offline(seed, "eval_rich", ctx=seed)
    from test_evaluation.golden import golden_plan_for

    calls: list[str] = []
    import common.adk.model as model_mod
    import common.llm.vertex as vx
    from test_evaluation.metrics import ragas_judge as rj

    def _spy(name):
        def f(*a, **k):
            calls.append(name)
            raise AssertionError(f"default scorer touched the LLM via {name}")
        return f

    monkeypatch.setattr(vx, "complete", _spy("vertex.complete"))
    monkeypatch.setattr(model_mod, "agent_model", _spy("agent_model"))
    monkeypatch.setattr(rj, "judge", _spy("ragas_judge.judge"))

    report = evaluate_pack(trace.bank, seed, golden_for(seed))
    plan_report = evaluate_plan(plan_trace.bank, seed, golden_plan_for(seed))

    assert calls == [], f"default scorer made LLM calls: {calls}"
    assert report.semantic is None  # judged tier never populated by the deterministic default path
    assert 0.0 <= report.pqs <= 1.0 and 0.0 <= plan_report.tps <= 1.0


# --- V3: the ADK-native judged tier is provider-sourced, creds-gated, offline-skipping ----------

def test_adk_native_judged_tier_skips_offline():
    from test_evaluation.eval.config import judged_criteria
    from test_evaluation.eval.runner import judged_available

    # VERTEX_* blanked by the session fixture → no provider-sourced judge model → empty criteria,
    # even though GOOGLE_CLOUD_PROJECT may be set (creds_available() alone is not enough).
    assert judged_criteria() == {}
    assert judged_available() is False


async def test_adk_native_judged_eval_returns_none_offline():
    from test_evaluation.eval.evalset import pack_eval_set as _pes
    from test_evaluation.eval.runner import run_judged_eval

    assert await run_judged_eval("test_evaluation", _pes()) is None


def test_semantic_rubrics_map_onto_adk_rubric_metric(monkeypatch):
    """V3 mapping (no creds/network): SEMANTIC_RUBRICS → rubric_based_final_response_quality_v1,
    judge model provider-sourced on every judged criterion (I8)."""
    from test_evaluation.eval import config, judge
    from test_evaluation.metrics.rubrics import SEMANTIC_RUBRICS

    monkeypatch.setattr(judge, "judge_model_id", lambda: "vertex_ai/claude-test")
    criteria = config.judged_criteria()

    assert set(criteria) == set(config.JUDGED_METRICS)
    rubric_metric = criteria["rubric_based_final_response_quality_v1"]
    assert {r.rubric_id for r in rubric_metric.rubrics} == set(SEMANTIC_RUBRICS)
    assert criteria["hallucinations_v1"].judge_model_options.judge_model == "vertex_ai/claude-test"
