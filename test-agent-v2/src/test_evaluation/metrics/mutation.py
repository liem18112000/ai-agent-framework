"""Fault-detection adequacy — the fault-class-coverage PROXY (real mutation is gated on execution)."""

from __future__ import annotations

from test_evaluation.models import FaultClassScore


def fault_class_coverage(scenarios: list[dict], behaviours: list[dict]) -> FaultClassScore:
    """`behaviours`: [{id, fault_classes:[...]}]. A class counts as aimed-at when its behaviour has"""
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
