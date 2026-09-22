"""Unit tests for the deterministic eval metrics (no LLM, no executor) — part of the PR gate."""

from __future__ import annotations

from test_evaluation.metrics.coverage import coverage_scores
from test_evaluation.metrics.entities import entities_recall
from test_evaluation.metrics.history import regressed
from test_evaluation.metrics.node_overlap import retrieval_scores
from test_evaluation.metrics.noise import drift_score
from test_evaluation.metrics.pqs import WEIGHTS, pqs
from test_evaluation.metrics.rubrics import cites_only_real_ids, no_invented_urls
from test_evaluation.metrics.trajectory import trajectory_score
from test_evaluation.models import PQSComponents


def test_trajectory_modes():
    assert trajectory_score(["g", "r", "a"], ["g", "r", "a"], "exact") == 1.0
    assert trajectory_score(["g", "x", "r", "a"], ["g", "r", "a"], "in_order") == 1.0
    assert trajectory_score(["g", "a", "r"], ["g", "r", "a"], "in_order") == 0.0
    assert trajectory_score(["a", "g"], ["g", "r", "a"], "any_order") == 2 / 3
    assert trajectory_score([], [], "in_order") == 1.0


def test_retrieval_scores_and_leak_gate():
    s = retrieval_scores({"a", "b", "c"}, {"a", "b", "d"}, {"c"})
    assert abs(s.precision - 2 / 3) < 1e-9 and abs(s.recall - 2 / 3) < 1e-9
    assert s.leaked == ["c"]
    assert s.missing == ["d"]
    assert retrieval_scores(set(), {"a"}).recall == 0.0
    assert retrieval_scores({"a"}, set()).recall == 1.0


def test_entities_recall():
    e = entities_recall(["luz_finance writes enrichmentstatus"], ["luz_finance", "MISSING"])
    assert e.recall == 0.5 and e.missing == ["MISSING"] and e.found == ["luz_finance"]


def test_pqs_weights_and_components():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9
    assert pqs(PQSComponents(**{k: 1.0 for k in WEIGHTS})).pqs == 1.0
    partial = pqs(PQSComponents(faithfulness=0.5))
    assert partial.pqs == 0.15 and partial.components.ctx_precision == 0.0


def test_drift_score():
    clean = "This ticket adds an invoice status check."
    bled = "This ticket adds an invoice status check and a ZIP import job."
    d = drift_score(clean, bled, ["ZIP import", "absent-term"])
    assert d.noise_sensitivity == 0.5 and d.leaked_terms == ["ZIP import"]
    assert drift_score(clean, clean, ["ZIP import"]).noise_sensitivity == 0.0


def test_rubric_id_and_url_fabrication_guards():
    pack = {"jira:LUZ-159312", "jira:LUZ-156281", "confluence:12345"}
    assert cites_only_real_ids("Grounded in LUZ-159312 and LUZ-156281.", pack).passed
    bad = cites_only_real_ids("See LUZ-999999 for details.", pack)
    assert not bad.passed and bad.invented == ["LUZ-999999"]
    assert no_invented_urls("see https://x/y", "docs at https://x/y here").passed
    assert not no_invented_urls("see https://evil/z", "no links").passed
    # M3: standards / CVE / RFC tokens share the Jira-key shape but aren't Jira keys (prefix not a pack project)
    assert cites_only_real_ids("Conforms to ISO-20022 and CVE-2021-1234 over UTF-8.", pack).passed


def test_regressed_band():
    assert regressed(0.80, 0.90, band=0.05) is True
    assert regressed(0.88, 0.90, band=0.05) is False


def test_coverage_scores_tolerates_id_less_behaviour():
    """L4: a golden behaviour missing 'id' must degrade, not raise KeyError into a 500."""
    cov = coverage_scores(
        [{"id": "s1", "kind": "happy", "source_refs": ["jira:LUZ-1"]}],
        [{"id": "jira:LUZ-1", "expected_partitions": ["happy"]}, {"expected_partitions": ["negative"]}],
    )
    assert cov.ac_recall == 1.0 and cov.uncovered == []
