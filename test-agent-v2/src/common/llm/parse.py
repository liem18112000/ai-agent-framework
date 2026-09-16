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


def loads_obj(raw: str) -> dict | None:
    """Parse a JSON OBJECT out of an LLM reply, tolerating a ```json fence AND surrounding prose — the
    recovery path when ADK's strict ``output_schema`` parser leaves state empty because the real model
    (Claude-on-Vertex) fenced or prefaced its JSON. Extract the outermost ``{...}`` and json.loads it."""
    text = raw.strip()
    if "```" in text:
        for block in text.split("```")[1::2]:  # the fenced blocks
            b = block.removeprefix("json").strip()
            if b.startswith("{"):
                text = b
                break
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def coerce_str(v):
    """Join a list to a string. LLMs sometimes return a scalar-typed field (e.g. a Question's"""
    return ", ".join(str(x) for x in v) if isinstance(v, list) else v
