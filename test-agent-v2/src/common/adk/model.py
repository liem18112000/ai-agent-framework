"""ADK `LlmAgent` model selection — a thin façade over the `ModelProvider` registry (C1/D10)."""

from __future__ import annotations

from common.adk.providers import get_provider


def agent_model(*, max_tokens: int | None = None):
    """The model for an ADK `LlmAgent`, per the configured provider (default Claude-on-Vertex)."""
    return get_provider().llm_agent_model(max_tokens=max_tokens)


def claude_llm(*, max_tokens: int = 6000):
    """Deprecated thin alias for the Claude provider's ADK model — kept for existing callers/tests."""
    from common.adk.providers.vertex_claude import VertexClaudeProvider

    return VertexClaudeProvider().llm_agent_model(max_tokens=max_tokens)
