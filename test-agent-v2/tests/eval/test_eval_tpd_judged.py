"""T2 + T3 + T4 (TPD) — the judged / composite tier (nightly, or on the `eval:` PR label).

T2's RAGAS brief faithfulness needs the optional `ragas` extra + a Vertex judge, so it SKIPS cleanly
when it isn't installed (reusing the shipped ragas_judge, same as the KGA judged tier). Everything
else — the full-engine TPS composite, Gherkin lint, oracle strength, fault-class coverage — is
DETERMINISTIC and always runs, scoring the SAME real plan+suite an LLM judge would, driven offline.
"""

from __future__ import annotations

import pytest

from test_evaluation.golden import load_golden_plans
from test_evaluation.metrics import ragas_judge
from test_evaluation.metrics.gherkin_lint import gherkin_lint
from test_evaluation.metrics.mutation import fault_class_coverage
from test_evaluation.metrics.oracle import oracle_strength
from test_evaluation.models import PlanEvalCase
from test_evaluation.plan_engine import evaluate_plan
from tests.eval.harness_tpd import run_plan_offline

_CASES = load_golden_plans()
_IDS = [c["seed"] for c in _CASES]


@pytest.fixture(scope="module", params=_CASES, ids=_IDS)
def scored(request):
    """Gather->refine->define->implement one golden plan, then score it through the runtime engine."""
    case = PlanEvalCase.from_dict(request.param)
    t = run_plan_offline(case.seed, case.fixture, depth=case.depth)
    return case, t, evaluate_plan(t.bank, t.ctx, case)


# --- T4: the TPS composite from the real per-seed components (deterministic) --- #
def test_tps_composite(scored):
    case, _t, r = scored
    assert set(r.components.as_dict()) == {                        # always carries all five components
        "fault_detection", "brief_groundedness", "coverage", "oracle_strength", "trajectory"}
    assert 0.0 <= r.tps <= 1.0
    assert r.components.coverage >= 0.8, f"{case.seed}: coverage {r.components.coverage}"
    assert r.components.brief_groundedness >= 0.5, f"{case.seed}: {r.components}"


# --- T3: Gherkin lint on the exported .feature (deterministic) --- #
def test_gherkin_well_formed(scored):
    case, t, _ = scored
    g = gherkin_lint(t.feature)
    assert g.scenarios > 0 and g.tagged == g.scenarios, f"{case.seed}: {g.issues}"


# --- T2/T3: oracle strength + fault-class coverage over the real suite (deterministic) --- #
def test_oracle_and_fault_proxy(scored):
    case, t, _ = scored
    o = oracle_strength(t.steps, tuple(case.pass_criteria))
    assert 0.0 <= o.score <= 1.0 and sum(o.distribution.values()) == len(
        [s for s in t.steps if s["expected"]])
    f = fault_class_coverage(t.scenarios, case.behaviours)
    assert 0.0 <= f.coverage <= 1.0                               # full-matrix suite aims at each class


# --- T2: RAGAS faithfulness over the brief (LLM — skips without the [eval] extra) --- #
def test_ragas_brief_faithfulness(scored):
    if not ragas_judge.available():
        pytest.skip("ragas not installed — runs only in the nightly/[eval] job")
    case, t, _ = scored
    scores = ragas_judge.judge(seed_summary=f"Test plan for {case.seed}", understanding=t.brief,
                               note_synopses=[s["title"] for s in t.scenarios],
                               reference=case.reference_brief)
    assert scores.faithfulness >= 0.5
