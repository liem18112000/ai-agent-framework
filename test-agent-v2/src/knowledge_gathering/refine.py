"""Knowledge-refinement domain logic — framework-neutral (extracted from executor/refine.py in C2)."""

from __future__ import annotations

import json


def wants_refine(text: str) -> bool:
    t = text.strip().lower()
    if t.startswith("refine"):
        return True
    if t.startswith("{"):
        try:
            d = json.loads(text)
        except json.JSONDecodeError:
            return False
        return "context_id" in d or "answers" in d
    return False
