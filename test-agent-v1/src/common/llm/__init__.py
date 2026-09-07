"""Shared LLM surface — Claude-on-Vertex plus the generic question/understanding generators.

Callers reach the model through `complete` (raw completion), `vertex_config` (env-driven
"is an LLM configured?" check), and the two generic generators (`claude_questions`,
`claude_understanding`) used by the refine engine. Agent-specific prompts/generators and
the distiller stay in each agent's own `llm` package.
"""

from common.llm.questions import claude_questions
from common.llm.understanding import claude_understanding
from common.llm.vertex import agenerate, complete, first_text, vertex_config

__all__ = [
    "agenerate",
    "claude_questions",
    "claude_understanding",
    "complete",
    "first_text",
    "vertex_config",
]
