"""Context Entities Recall (deterministic tier) — did the pack surface the right domain entities?"""

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
