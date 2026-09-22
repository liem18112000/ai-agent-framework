"""Test-Plan Score — the single weighted composite for the TPD, plus its always-emitted components."""

from __future__ import annotations

from test_evaluation.models import TPSComponents, TPSResult

TPS_WEIGHTS = {
    "fault_detection": 0.30,
    "brief_groundedness": 0.25,
    "coverage": 0.20,
    "oracle_strength": 0.15,
    "trajectory": 0.10,
}


def tps(components: TPSComponents) -> TPSResult:
    """Weighted mean of the surface scores; the TPSResult always carries the components too."""
    score = sum(w * getattr(components, k) for k, w in TPS_WEIGHTS.items())
    return TPSResult(tps=round(score, 3), components=components)
