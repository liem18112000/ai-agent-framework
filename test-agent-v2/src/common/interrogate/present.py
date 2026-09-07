"""Request/question presentation helpers shared by both agents' executors.

`extract_ctx` pulls a context id out of an inbound A2A request (JSON body, a `run-…`
token, or the second word after a known command); `render_questions` formats an open
question round for the human. Both are pure and agent-agnostic — each agent binds its own
command prefixes / header via a thin wrapper (see knowledge_gathering.executor.refine and
test_plan_definition.executor.define).
"""

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
        return parts[1]
    return None


def render_questions(context_id: str, open_qs, *, header: str) -> str:
    """Format one open question round (id · round · options · recommendation) for the human."""
    lines = [
        (
            f"{header} for context {context_id} "
            f"({open_qs[0].round} round) — reply e.g. `{open_qs[0].id}: <your choice>`:"
        ),
        "",
    ]
    for q in open_qs:
        lines.append(f"- {q.id} [{q.round}] {q.question}")
        for opt in q.options:
            lines.append(f"    · {opt.get('label')} — {opt.get('implication', '')}")
        if q.recommendation:
            lines.append(f"    recommendation: {q.recommendation}")
    return "\n".join(lines)
