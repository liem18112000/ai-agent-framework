"""Request/question presentation helpers shared by both agents' executors."""

from __future__ import annotations

import json
import re


def extract_ctx(text: str, prefixes: tuple[str, ...]) -> str | None:
    """Best-effort context id from request text: JSON `context_id`, a `run-…` token, or `<cmd> <id>`."""
    t = text.strip()
    if t.startswith("{"):
        try:
            return json.loads(t).get("context_id")
        except json.JSONDecodeError:
            return None
    if m := re.search(r"\b(run-\w+)\b", t):
        return m.group(1)
    parts = t.split()
    if len(parts) > 1 and parts[0].lower() in prefixes:
        # skip any chained command noun (e.g. "evaluate plan <ctx>") → first non-command token
        return next((tok for tok in parts[1:] if tok.lower() not in prefixes), None)
    return None


def render_questions(context_id: str, open_qs, *, header: str) -> str:
    """Format one open question round (id · round · options · recommendation) for the human."""
    lines = [f"{header} for context {context_id} ({open_qs[0].round} round) — reply e.g. `{open_qs[0].id}: <your choice>`:", ""]
    for q in open_qs:
        lines.append(f"- {q.id} [{q.round}] {q.question}")
        for opt in q.options:
            lines.append(f"    · {opt.get('label')} — {opt.get('implication', '')}")
        if q.recommendation:
            lines.append(f"    recommendation: {q.recommendation}")
    return "\n".join(lines)
