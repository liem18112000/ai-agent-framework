"""ADK `LlmAgent` model selection — a thin façade over the `ModelProvider` registry (C1/D10)."""

from __future__ import annotations

from common.adk.providers import get_provider


def agent_model(*, max_tokens: int | None = None, tier: str = "default"):
    """The model for an ADK `LlmAgent`, per the configured provider (default Claude-on-Vertex).
    ``tier="fast"`` requests a cheaper model for classification/judging sub-tasks (inert unless the
    provider has one configured, e.g. VERTEX_MODEL_FAST)."""
    return get_provider().llm_agent_model(max_tokens=max_tokens, tier=tier)


def model_configured() -> bool:
    """Provider-agnostic "is the model configured?" gate — the replacement for the raw
    `vertex_config() is not None` checks (choose LLM vs heuristic). Delegates to the port."""
    return get_provider().is_configured()


def complete(prompt: str, *, max_tokens: int, cache_prefix: str | None = None,
             tier: str = "default") -> str:
    """Provider-agnostic single-shot completion — routes the engine text path through the port so
    the LLM stays swappable. `cache_prefix` (optional) forwards a stable prompt-caching prefix;
    `tier="fast"` requests the provider's cheaper model (inert unless one is configured)."""
    return get_provider().complete(prompt, max_tokens=max_tokens, cache_prefix=cache_prefix, tier=tier)