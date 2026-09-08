"""E0 + E1 — the deterministic PR gate. No LLM, no network."""

from __future__ import annotations

import pytest

from test_evaluation.golden import load_golden
from test_evaluation.metrics.node_overlap import retrieval_scores
from test_evaluation.metrics.trajectory import trajectory_score
from tests.eval.harness import recorded_client, run_gather_offline

_CASES = load_golden()
_IDS = [c["seed"] for c in _CASES]


@pytest.fixture(scope="module", params=_CASES, ids=_IDS)
def trace(request):
    """One offline gather per golden seed (cached per seed across the assertions below)."""
    case = request.param
    t = run_gather_offline(case["seed"], client=recorded_client(case["fixture"]),
                           text=f"gather {case['seed']} depth {case['depth']}")
    return case, t


def test_tier_trajectory(trace):
    case, t = trace
    assert trajectory_score(t.tiers, case["expected_tiers"], "in_order") == 1.0, \
        f"{case['seed']}: tiers {t.tiers} != expected {case['expected_tiers']}"


def test_fetch_kind_trajectory(trace):
    case, t = trace
    assert trajectory_score(t.fetch_kinds, case["expected_fetch_kinds"], "any_order") == 1.0, \
        f"{case['seed']}: fetch_kinds {t.fetch_kinds} missing {case['expected_fetch_kinds']}"


def test_retrieval_scores(trace):
    case, t = trace
    s = retrieval_scores(t.node_ids, set(case["relevant_node_ids"]),
                         set(case["must_not_retrieve_ids"]))
    assert s.leaked == [], f"{case['seed']}: hard-negative leaked {s.leaked} (memory bleed)"
    assert s.recall >= case["min_recall"], \
        f"{case['seed']}: recall {s.recall:.2f} < {case['min_recall']} (missing {s.missing})"
    assert s.precision >= case["min_precision"], \
        f"{case['seed']}: precision {s.precision:.2f} < {case['min_precision']}"
