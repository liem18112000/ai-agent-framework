"""Claude-on-Vertex synopsis of a gathered node."""

from __future__ import annotations

from common.models import Note


def claude_distill(note: Note, text: str) -> str:
    # Lazy import — see common.llm.questions.claude_questions for the cycle rationale.
    from common.adk.model import complete

    prompt = f"Summarize this {note.type} for a QA engineer in 2 sentences:\n\n{text[:4000]}"
    return complete(prompt, max_tokens=200).strip()
