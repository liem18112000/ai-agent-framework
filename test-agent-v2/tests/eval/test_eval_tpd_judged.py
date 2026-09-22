"""T2 + T3 + T4 (TPD) — the judged / composite tier (nightly, or on the `eval:` PR label)."""

from __future__ import annotations

import pytest

from test_evaluation.engine import evaluate_plan
from test_evaluation.golden import load_golden_plans
from test_evaluation.metrics import ragas_judge
from test_evaluation.metrics.gherkin_lint import gherkin_lint
from test_evaluation.metrics.mutation import fault_class_coverage
from test_evaluation.metrics.oracle import oracle_strength
from test_evaluation.models import PlanEvalCase
from tests.eval.harness_tpd import run_plan_offline

_CASES = load_golden_plans()
_IDS = [c["seed"] for c in _CASES]


@pytest.fixture(scope="module", params=_CASES, ids=_IDS)
def scored(request):
    """Gather->refine->define->implement one golden plan, then score it through the runtime engine."""
    case = PlanEvalCase.from_dict(request.param)
    t = run_plan_offline(case.seed, case.fixture, depth=case.depth)
    return case, t, evaluate_plan(t.bank, t.ctx, case)


def test_tps_composite(scored):
    case, _t, r = scored
    assert set(r.components.as_dict()) == {
        "fault_detection", "brief_groundedness", "coverage", "oracle_strength", "trajectory"}
    assert 0.0 <= r.tps <= 1.0
    assert r.components.coverage >= 0.8, f"{case.seed}: coverage {r.components.coverage}"
    assert r.components.brief_groundedness >= 0.5, f"{case.seed}: {r.components}"


def test_gherkin_well_formed(scored):
    case, t, _ = scored
    g = gherkin_lint(t.feature)
    assert g.scenarios > 0 and g.tagged == g.scenarios, f"{case.seed}: {g.issues}"


def test_oracle_and_fault_proxy(scored):
    case, t, _ = scored
    o = oracle_strength(t.steps, tuple(case.pass_criteria))
    assert 0.0 <= o.score <= 1.0 and sum(o.distribution.values()) == len(
        [s for s in t.steps if s["expected"]])
    f = fault_class_coverage(t.scenarios, case.behaviours)
    assert 0.0 <= f.coverage <= 1.0


def test_ragas_brief_faithfulness(scored):
    # V1 — route RAGAS through the PROVIDER-sourced judge (no silent OpenAI default, I8). Skips
    # cleanly offline: build_ragas_llm() is None without the `eval` extra OR VERTEX_* creds.
    from test_evaluation.eval.judge import build_ragas_embeddings, build_ragas_llm

    llm = build_ragas_llm()
    if llm is None:
        pytest.skip("no provider-sourced RAGAS judge (`eval` extra or VERTEX_* creds absent)")
    case, t, _ = scored
    scores = ragas_judge.judge(seed_summary=f"Test plan for {case.seed}", understanding=t.brief,
                               note_synopses=[s["title"] for s in t.scenarios],
                               reference=case.reference_brief,
                               llm=llm, embeddings=build_ragas_embeddings())
    assert scores.faithfulness >= 0.5
