"""Test-Plan Score — the single weighted composite for the TPD, plus its always-emitted components.

The TPD twin of pqs.py. Fault-detection + brief-groundedness weigh highest because the real TPD
incidents were a bled brief + shallow oracles, not too-few scenarios: a thin suite is a VISIBLE
failure a human catches; a full-looking-but-shallow suite (all oracles `assert 200`) or a
confidently-bled brief (scopes the excluded nodes) fools you. While mutation is a proxy, the
FaultDetection term folds in oracle-strength; re-split once real mutation lands. TPS_WEIGHTS keys ==
TPSComponents field names.
"""

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
