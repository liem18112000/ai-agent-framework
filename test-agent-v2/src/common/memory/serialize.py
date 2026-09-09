"""(de)serialization + cross-run merge for notes and refinement records."""

from __future__ import annotations

from dataclasses import fields

from common.models import Answer, Insight, LinkRecord, Note, Question


def note_from_dict(d: dict) -> Note:
    names = {f.name for f in fields(Note)} - {"links"}
    return Note(**{k: v for k, v in d.items() if k in names}, links=[LinkRecord(**lr) for lr in d.get("links", [])])


def _from(cls, d: dict):
    """Build a dataclass from a dict, ignoring unknown keys (schema-drift tolerant)."""
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in d.items() if k in names})


def question_from_dict(d: dict) -> Question: return _from(Question, d)


def answer_from_dict(d: dict) -> Answer: return _from(Answer, d)


def insight_from_dict(d: dict) -> Insight: return _from(Insight, d)


def merge_notes(old: Note, new: Note) -> Note:
    """Union links (by canonical) + backlinks; new wins on conflict; shallowest depth."""
    by_canon = {lr.canonical_url: lr for lr in old.links}
    for lr in new.links:
        by_canon[lr.canonical_url] = lr
    new.links = list(by_canon.values())
    new.backlinks = sorted(set(old.backlinks) | set(new.backlinks))
    new.depth = min(old.depth, new.depth)
    return new
