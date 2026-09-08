"""Pack Quality Score — the single weighted composite, plus its always-emitted components."""

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
    """Weighted mean of the surface scores. The PQSResult always carries the components too — a bare"""
    score = sum(w * getattr(components, k) for k, w in WEIGHTS.items())
    return PQSResult(pqs=round(score, 3), components=components)
