"""Claude-on-Vertex synopsis of a gathered node."""

from __future__ import annotations

from common.llm.vertex import complete
from common.models import Note


def claude_distill(note: Note, text: str, *, project: str, location: str, model: str) -> str:
    prompt = f"Summarize this {note.type} for a QA engineer in 2 sentences:\n\n{text[:4000]}"
    return complete(prompt, project=project, location=location, model=model, max_tokens=200).strip()
