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


def _brace_spans(text: str):
    """Yield every balanced top-level ``{...}`` substring, skipping braces inside JSON strings.

    A plain first-``{``→last-``}`` slice mis-parses when the model emits prose+JSON or multiple ``{}``
    blocks (e.g. ``{example}`` in the preamble, then the real payload); this walks the text so each
    complete object is a candidate. String-aware so a ``}`` inside a value never miscounts the depth."""
    depth = start = 0
    started = in_str = esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start, started = i, True
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and started:
                yield text[start:i + 1]
                started = False


def loads_obj(raw: str) -> dict | None:
    """Parse a JSON OBJECT out of an LLM reply, tolerating a ```json fence AND surrounding prose — the
    recovery path when ADK's strict ``output_schema`` parser leaves state empty because the real model
    (Claude-on-Vertex) fenced or prefaced its JSON. Scan every balanced ``{...}`` span and return the
    LARGEST one that parses to a dict (the real payload dwarfs any ``{example}`` in the prose)."""
    # ponytail: largest-valid-dict heuristic; if a caller ever needs schema-exact matching, pass expected keys.
    best: dict | None = None
    best_len = -1
    for span in _brace_spans(raw):
        try:
            data = json.loads(span)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and len(span) > best_len:
            best, best_len = data, len(span)
    return best


def coerce_str(v):
    """Join a list to a string. LLMs sometimes return a scalar-typed field (e.g. a Question's"""
    return ", ".join(str(x) for x in v) if isinstance(v, list) else v
