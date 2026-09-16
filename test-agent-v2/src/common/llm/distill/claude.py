"""Claude-on-Vertex synopsis of a gathered node."""

from __future__ import annotations

from common.models import Note


def claude_distill(note: Note, text: str) -> str:
    # Lazy import — see common.llm.questions.claude_questions for the cycle rationale.
    from common.adk.model import complete

    # Give the model the node's title (what it's summarizing) and tell it to keep the load-bearing
    # specifics; widen the input window so a long ticket/spec isn't distilled from only its first page.
    title = f" titled '{note.title}'" if note.title else ""
    prompt = (
        f"Summarize this {note.type}{title} for a QA engineer in 2 sentences, keeping any concrete "
        f"rules, limits, IDs, endpoints and error/boundary conditions it states:\n\n{text[:8000]}"
    )
    return complete(prompt, max_tokens=200).strip()
