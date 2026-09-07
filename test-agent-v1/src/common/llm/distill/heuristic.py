"""Heuristic (no-LLM) synopsis."""

from __future__ import annotations

from common.models import Note


def heuristic_distill(note: Note, text: str = "") -> str:
    first_line = (text or "").strip().splitlines()[0][:240] if text.strip() else ""
    in_scope = sum(lr.in_scope for lr in note.links)
    tail = f"{len(note.links)} links, {in_scope} in-scope."
    return f"{first_line}  ({tail})" if first_line else f"{note.title} — {tail}"
