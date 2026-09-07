"""Unit tests for the deterministic TPD eval metrics (no LLM, no executor) — part of the PR gate.

Locks the metric math itself; the seed-driven assertions live in test_eval_tpd_deterministic.py.
Scope reuses the KGA node-overlap arithmetic (tested there); here we cover the TPD-specific metrics.
"""

from __future__ import annotations

from test_evaluation.metrics.coverage import coverage_scores
from test_evaluation.metrics.gherkin_lint import gherkin_lint
from test_evaluation.metrics.mutation import fault_class_coverage
from test_evaluation.metrics.oracle import classify, oracle_strength
from test_evaluation.metrics.placeholders import placeholder_scan
from test_evaluation.metrics.tps import TPS_WEIGHTS, tps
from test_evaluation.models import TPSComponents


# --- coverage: AC-recall + matrix completeness + traceability --- #
def test_coverage_scores():
    behaviours = [{"id": "jira:A", "expected_partitions": ["happy", "negative", "boundary", "error"]},
                  {"id": "jira:B", "expected_partitions": ["happy", "negative"]}]
    scenarios = [{"id": "s1", "kind": "happy", "source_refs": ["jira:A"]},
                 {"id": "s2", "kind": "negative", "source_refs": ["jira:A"]},
                 {"id": "s3", "kind": "happy", "source_refs": ["jira:B"]}]  # B misses 'negative'
    c = coverage_scores(scenarios, behaviours, valid_refs={"jira:A", "jira:B"})
    assert c.ac_recall == 1.0                                   # both behaviours have a scenario
    assert c.per_behaviour["jira:A"] == 0.5                     # 2 of 4 partitions
    assert c.per_behaviour["jira:B"] == 0.5                     # 1 of 2 partitions
    assert c.matrix_completeness == 0.5 and c.traceability == 1.0


def test_coverage_flags_uncovered_and_untraceable():
    behaviours = [{"id": "jira:A", "expected_partitions": ["happy"]},
                  {"id": "jira:B", "expected_partitions": ["happy"]}]
    scenarios = [{"id": "s1", "kind": "happy", "source_refs": ["jira:A"]},
                 {"id": "s2", "kind": "happy", "source_refs": ["jira:GHOST"]}]  # not a real ref
    c = coverage_scores(scenarios, behaviours, valid_refs={"jira:A", "jira:B"})
    assert c.ac_recall == 0.5 and c.uncovered == ["jira:B"]
    assert c.untraceable == ["s2"] and c.traceability == 0.5


# --- oracle strength --- #
def test_oracle_classify_and_strength():
    assert classify("a 4xx status is returned") == "weak"
    assert classify("the tracking row reaches CREDIT_CARD_CHARGED_PENDING") == "strong"
    assert classify("the stored invoice status is correct", ("stored invoice status",)) == "strong"
    assert classify("the end state is asserted") == "medium"
    o = oracle_strength([{"expected": "the response status is 2xx"},
                         {"expected": "the row reaches CREDIT_CARD_CHARGED_PENDING"}])
    assert o.distribution == {"strong": 1, "medium": 0, "weak": 1} and o.score == 0.5
    assert oracle_strength([]).score == 0.0                     # nothing asserted


# --- placeholder leak + which-path provenance --- #
def test_placeholder_scan():
    clean = placeholder_scan([{"title": "Charge job — full path"}], [{"expected": "End-state verified"}],
                             [{"spec": {"id": "acc-1"}}])
    assert clean.passed and clean.provenance == "llm"
    leaked = placeholder_scan([{"title": "Charge job — happy path"}], [{"expected": "PASS_METRIC"}],
                              [{"spec": {"fields": {"id": "<generated>"}}}], detail=True)
    assert not leaked.passed                                    # tokens leaked AND heuristic path
    assert "PASS_METRIC" in leaked.leaked_tokens and "<generated>" in leaked.leaked_tokens
    assert leaked.provenance == "heuristic"


# --- gherkin lint --- #
def test_gherkin_lint():
    good = "Feature: X\n\n  @happy @api\n  Scenario: happy\n    Given a thing\n    When act\n    Then ok\n"
    g = gherkin_lint(good)
    assert g.passed and g.scenarios == 1 and g.tagged == 1
    bad = "Feature: X\n\n  Scenario: untagged\n    When act\n    Then ok\n"
    assert not gherkin_lint(bad).passed                         # scenario without @kind @methodology


# --- fault-class coverage proxy --- #
def test_fault_class_coverage():
    behaviours = [{"id": "jira:A", "fault_classes": ["wrong day", "no persist"]}]
    aimed = [{"kind": "negative", "source_refs": ["jira:A"]}]   # a non-happy scenario exists for A
    assert fault_class_coverage(aimed, behaviours).coverage == 1.0
    happy_only = [{"kind": "happy", "source_refs": ["jira:A"]}]
    fc = fault_class_coverage(happy_only, behaviours)
    assert fc.coverage == 0.0 and set(fc.missing) == {"wrong day", "no persist"}


# --- tps composite --- #
def test_tps_weights_and_components():
    assert abs(sum(TPS_WEIGHTS.values()) - 1.0) < 1e-9
    assert tps(TPSComponents(**{k: 1.0 for k in TPS_WEIGHTS})).tps == 1.0
    partial = tps(TPSComponents(fault_detection=1.0))          # only the .30 term
    assert partial.tps == 0.3 and partial.components.coverage == 0.0
