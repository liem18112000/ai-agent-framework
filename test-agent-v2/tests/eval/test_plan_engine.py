"""Tests for the TPD evaluation surface — the plan_engine + the ADK EvaluatorAgent's plan path."""

from __future__ import annotations

from test_evaluation.engine import evaluate_plan
from test_evaluation.models import PlanEvalCase
from tests.conftest import drive_adk
from tests.eval.harness_tpd import run_plan_offline


def test_evaluate_plan_scores_a_clean_suite():
    t = run_plan_offline("LUZ-501", "eval_rich")
    case = PlanEvalCase.from_dict({
        "seed": "LUZ-501",
        "in_scope_ids": ["jira:LUZ-501", "jira:LUZ-502", "jira:LUZ-503"],
        "behaviours": [{"id": "jira:LUZ-501", "expected_partitions": ["happy", "negative", "boundary", "error"]},
                       {"id": "jira:LUZ-502", "expected_partitions": ["happy"]},
                       {"id": "jira:LUZ-503", "expected_partitions": ["happy"]}],
    })
    r = evaluate_plan(t.bank, t.ctx, case)
    assert r.scope.leaked == [] and r.scope.precision == 1.0
    assert r.coverage.ac_recall == 1.0
    assert r.rubrics.cites_only_real_ids.passed
    assert 0.0 <= r.tps <= 1.0 and r.components.trajectory == 1.0


def test_evaluate_plan_flags_a_scope_leak():
    """A must_not_scope id that the plan scoped is a hard fail — the define-brief-scoping guard."""
    t = run_plan_offline("LUZ-701", "eval_bleed")
    scoped = t.plan.scope[0]
    case = PlanEvalCase.from_dict({"seed": "LUZ-701", "in_scope_ids": ["jira:LUZ-702"],
                                   "must_not_scope_ids": [scoped]})
    r = evaluate_plan(t.bank, t.ctx, case)
    assert r.scope.leaked == [scoped]


async def test_agent_evaluates_plan_by_ctx(monkeypatch):
    import test_evaluation.agent as agent_mod

    t = run_plan_offline("LUZ-501", "eval_rich")
    monkeypatch.setattr(agent_mod, "build_bank", lambda: t.bank)
    out = await drive_adk(agent_mod.build_root_agent, f"evaluate plan {t.ctx}", session_id=t.ctx)
    assert "Test-Plan Score" in out and "Components:" in out
