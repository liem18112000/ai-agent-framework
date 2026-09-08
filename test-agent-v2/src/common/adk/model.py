"""ADK `LlmAgent` model selection — a thin façade over the `ModelProvider` registry (C1/D10).

`agent_model()` returns the configured provider's ADK model (a `LiteLlm` for Claude-on-Vertex), or
`None` when the provider is unconfigured (the master "no LLM → heuristic path" signal, invariant I7).
All model construction lives in `common/adk/providers/` (invariant I8) — this module only dispatches.
"""

from __future__ import annotations

from common.adk.providers import get_provider


def agent_model(*, max_tokens: int | None = None):
    """The model for an ADK `LlmAgent`, per the configured provider (default Claude-on-Vertex).

    Returns the provider's model object (a `LiteLlm`), or `None` when unconfigured → the caller uses
    the heuristic path (I7)."""
    return get_provider().llm_agent_model(max_tokens=max_tokens)


def claude_llm(*, max_tokens: int = 6000):
    """Deprecated thin alias for the Claude provider's ADK model — kept for existing callers/tests.

    Prefer `agent_model()` (provider-dispatched). Returns `None` when VERTEX_* is unset (heuristic, I7).
    """
    from common.adk.providers.vertex_claude import VertexClaudeProvider

    return VertexClaudeProvider().llm_agent_model(max_tokens=max_tokens)
