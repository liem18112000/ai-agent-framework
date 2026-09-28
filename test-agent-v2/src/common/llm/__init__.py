"""Shared LLM surface — Claude-on-Vertex plus the generic question/understanding generators."""

from common.llm.questions import claude_questions
from common.llm.understanding import claude_understanding
from common.llm.vertex import complete, first_text, vertex_config

__all__ = [
    "claude_questions",
    "claude_understanding",
    "complete",
    "first_text",
    "vertex_config",
]
