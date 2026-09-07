"""Fault-detection adequacy — the fault-class-coverage PROXY (real mutation is gated on execution).

The gold standard is mutation score (PIT), which needs the scenarios to actually RUN against the
SUT — the execution stage (RESEARCH-agentic-qa-enhancements.md Pillar 2) that does not exist yet.
Until it ships, this is the honest stand-in: of the golden behaviours' known fault classes, how many
has the suite AIMED a scenario at — proxied by the behaviour having a non-happy (negative/boundary/
error) scenario. A checklist, not a kill-count; the report says so.
"""

from __future__ import annotations

from test_evaluation.models import FaultClassScore


def fault_class_coverage(scenarios: list[dict], behaviours: list[dict]) -> FaultClassScore:
    """`behaviours`: [{id, fault_classes:[...]}]. A class counts as aimed-at when its behaviour has
    at least one non-happy scenario (the partition that would exercise the fault)."""
    classes = [(b["id"], fc) for b in behaviours for fc in b.get("fault_classes", [])]
    if not classes:
        return FaultClassScore(coverage=1.0, covered=[], missing=[])
    covered, missing = [], []
    for bid, fc in classes:
        aimed = any(bid in sc.get("source_refs", []) and sc.get("kind") != "happy"
                    for sc in scenarios)
        (covered if aimed else missing).append(fc)
    return FaultClassScore(coverage=round(len(covered) / len(classes), 3),
                           covered=covered, missing=missing)
