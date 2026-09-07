"""RAGAS-style Context Precision / Recall / F1 by node-id SET OVERLAP — no LLM.

The KGA's retrieved units are identified nodes (`jira:LUZ-…`, `confluence:…`, `codegraph:…`),
so precision/recall reduce to cheap deterministic set arithmetic against a golden id set — no
LLM judge needed. `leaked` is the hard-negative (memory-bleed) gate: any id in `hard_neg` that
was retrieved MUST fail the run.
"""

from __future__ import annotations

from test_evaluation.models import RetrievalScore


def retrieval_scores(retrieved: set[str], relevant: set[str],
                     hard_neg: set[str] = frozenset()) -> RetrievalScore:
    """Precision/recall/f1 of `retrieved` vs `relevant`, plus any leaked hard-negatives.

    No relevant set → recall 1.0 (nothing to find). No retrieved set → precision 0.0.
    `leaked` (sorted) must be empty; a non-empty list is a precision/noise failure.
    """
    tp = retrieved & relevant
    precision = len(tp) / len(retrieved) if retrieved else 0.0
    recall = len(tp) / len(relevant) if relevant else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return RetrievalScore(
        precision=precision,
        recall=recall,
        f1=f1,
        leaked=sorted(retrieved & hard_neg),
        missing=sorted(relevant - retrieved),
    )
