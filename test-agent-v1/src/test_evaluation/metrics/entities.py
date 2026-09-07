"""Context Entities Recall (deterministic tier) — did the pack surface the right domain entities?

Node-overlap counts CONTAINERS (which tickets/pages); this counts the concrete named things the
pack must mention — Jira keys, repo/component names, endpoints, enums. Code identifiers and issue
keys are exact-match-friendly, so substring matching catches most cases with no LLM. Reach for
`ragas.metrics.ContextEntitiesRecall` only for fuzzy variants. `missing` names the dropped referent.
"""

from __future__ import annotations

from test_evaluation.models import EntitiesScore


def entities_recall(note_texts: list[str], key_entities: list[str]) -> EntitiesScore:
    """Fraction of `key_entities` that appear (case-insensitive substring) in the pack's note text."""
    hay = " ".join(note_texts).lower()
    found = [e for e in key_entities if e.lower() in hay]
    return EntitiesScore(
        recall=len(found) / len(key_entities) if key_entities else 1.0,
        found=found,
        missing=[e for e in key_entities if e.lower() not in hay],
    )
