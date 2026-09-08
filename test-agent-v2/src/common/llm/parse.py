"""Parse a JSON array out of an LLM reply, tolerating a ```json code fence."""

from __future__ import annotations

import json


def loads_array(raw: str) -> list | None:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1].removeprefix("json").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def coerce_str(v):
    """Join a list to a string. LLMs sometimes return a scalar-typed field (e.g. a Question's"""
    return ", ".join(str(x) for x in v) if isinstance(v, list) else v
