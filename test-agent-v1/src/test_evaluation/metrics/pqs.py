"""Pack Quality Score — the single weighted composite, plus its always-emitted components.

Faithfulness + precision weigh highest because the real KGA incidents were bleed + drift, not
missing recall: a thin pack is a VISIBLE failure a human catches; a high-recall-but-bled pack looks
full and fools you, so the silent modes get the heavier weights. Trajectory is lowest — E0 already
gates it deterministically, so here it's a tie-breaker. WEIGHTS keys == PQSComponents field names.
"""

from __future__ import annotations

from test_evaluation.models import PQSComponents, PQSResult

WEIGHTS = {
    "faithfulness": 0.30,
    "ctx_precision": 0.25,
    "ctx_recall": 0.20,
    "relevancy": 0.15,
    "trajectory": 0.10,
}


def pqs(components: PQSComponents) -> PQSResult:
    """Weighted mean of the surface scores. The PQSResult always carries the components too — a bare
    number hides which surface regressed."""
    score = sum(w * getattr(components, k) for k, w in WEIGHTS.items())
    return PQSResult(pqs=round(score, 3), components=components)
