"""Parse a JSON array out of an LLM reply, tolerating a ```json code fence.

Returns the list, or None when the reply isn't a JSON array — the "fall back to heuristic"
signal the selection factories key off.
"""

from __future__ import annotations

import json


def loads_array(raw: str) -> list | None:
    text = raw.strip()
    if text.startswith("```"):  # strip a ```json fence if the model added one
        text = text.split("```", 2)[1].removeprefix("json").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def coerce_str(v):
    """Join a list to a string. LLMs sometimes return a scalar-typed field (e.g. a Question's
    `applies_to`, contract `str`) as a JSON list; left as a list it later becomes an unhashable
    source_ref and crashes plan assembly. A non-list passes through unchanged."""
    return ", ".join(str(x) for x in v) if isinstance(v, list) else v
