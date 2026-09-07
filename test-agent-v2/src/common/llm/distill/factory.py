"""Select the distiller from env — Claude on Vertex if configured, else heuristic."""

from __future__ import annotations

from common.llm.distill.claude import claude_distill
from common.llm.distill.heuristic import heuristic_distill
from common.llm.vertex import vertex_config
from common.models import Note


def make_distiller():
    cfg = vertex_config()
    if not cfg:
        return heuristic_distill
    proj, loc, model = cfg

    def distiller(note: Note, text: str) -> str:
        if len(text or "") < 800:
            return heuristic_distill(note, text)
        return claude_distill(note, text, project=proj, location=loc, model=model)

    return distiller
