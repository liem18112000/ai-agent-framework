"""Coverage adequacy — did the suite cover the behaviours and their partitions? (deterministic)"""

from __future__ import annotations

from collections.abc import Iterable

from test_evaluation.models import CoverageScore


def _frac(hit: set, whole: set) -> float:
    return len(hit & whole) / len(whole) if whole else 1.0


def coverage_scores(scenarios: list[dict], behaviours: list[dict],
                    valid_refs: Iterable[str] = ()) -> CoverageScore:
    """`valid_refs` = the real pack node-id set for traceability (defaults to the behaviour ids)."""
    beh = {b["id"] for b in behaviours if "id" in b}
    covered = {r for sc in scenarios for r in sc.get("source_refs", [])}
    per = {b["id"]: _frac({sc.get("kind") for sc in scenarios if b["id"] in sc.get("source_refs", [])},
                          set(b.get("expected_partitions", []))) for b in behaviours if "id" in b}
    valid = set(valid_refs) or beh
    untraceable = sorted({sc.get("id", "") for sc in scenarios
                          if not set(sc.get("source_refs", [])) & valid})
    return CoverageScore(
        ac_recall=_frac(covered, beh),
        matrix_completeness=sum(per.values()) / len(per) if per else 1.0,
        traceability=1.0 - len(untraceable) / len(scenarios) if scenarios else 1.0,
        per_behaviour=per, uncovered=sorted(beh - covered), untraceable=untraceable,
    )
