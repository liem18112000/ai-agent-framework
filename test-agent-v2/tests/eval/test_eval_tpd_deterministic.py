"""T0 + T1 — the deterministic TPD PR gate. No LLM, no network."""

from __future__ import annotations

import pytest

from test_evaluation.golden import load_golden_plans
from test_evaluation.metrics.coverage import coverage_scores
from test_evaluation.metrics.node_overlap import retrieval_scores
from test_evaluation.metrics.placeholders import placeholder_scan
from test_evaluation.metrics.trajectory import trajectory_score
from test_evaluation.models import PlanEvalCase
from tests.eval.harness_tpd import run_plan_offline

_CASES = load_golden_plans()
_IDS = [c["seed"] for c in _CASES]


@pytest.fixture(scope="module", params=_CASES, ids=_IDS)
def trace(request):
    """One offline define+implement per golden plan (cached per seed across the assertions)."""
    d = request.param
    return PlanEvalCase.from_dict(d), run_plan_offline(d["seed"], d["fixture"], depth=d.get("depth", 1))


def test_trajectory(trace):
    case, t = trace
    assert trajectory_score(t.trajectory, case.expected_trajectory, "in_order") == 1.0, \
        f"{case.seed}: trajectory {t.trajectory} != {case.expected_trajectory}"


def test_scope(trace):
    case, t = trace
    s = retrieval_scores(set(t.plan.scope), set(case.in_scope_ids), set(case.must_not_scope_ids))
    assert s.leaked == [], f"{case.seed}: scope leaked a must-not-scope id {s.leaked} (define-brief bug)"
    assert s.precision >= case.min_scope_precision, \
        f"{case.seed}: scope precision {s.precision:.2f} < {case.min_scope_precision}"


def test_coverage(trace):
    case, t = trace
    c = coverage_scores(t.scenarios, case.behaviours)
    assert c.ac_recall >= case.min_ac_recall, \
        f"{case.seed}: AC-recall {c.ac_recall:.2f} < {case.min_ac_recall} (uncovered {c.uncovered})"
    assert c.matrix_completeness >= 0.8, f"{case.seed}: matrix completeness {c.matrix_completeness:.2f}"
    assert c.traceability >= case.min_traceability, \
        f"{case.seed}: traceability {c.traceability:.2f} < {case.min_traceability} (untraceable {c.untraceable})"


def test_placeholders(trace):
    case, t = trace
    p = placeholder_scan(t.scenarios, t.steps, t.test_data, detail=False)
    assert p.passed and p.provenance == "heuristic", f"{case.seed}: {p}"
    assert not placeholder_scan(t.scenarios, t.steps, t.test_data, detail=True).passed
