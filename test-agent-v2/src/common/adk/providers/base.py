"""`ModelProvider` — the one documented extension point for "which model, reached how" (C1/D10, I8)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ModelProvider(Protocol):
    """Model access for the ADK layer. All model construction (LiteLlm / google.adk.models) lives in"""

    name: str

    def is_configured(self) -> bool:
        """True when the provider's transport is configured (replaces the raw `vertex_config()` gate,"""
        ...

    def llm_agent_model(self, *, max_tokens: int | None = None, tier: str = "default"):
        """The model object for an ADK `LlmAgent` (a `LiteLlm` for Claude-on-Vertex), or `None` when
        unset. ``tier="fast"`` MAY select a cheaper/faster model for classification/judging sub-tasks;
        a provider without a fast tier simply returns its default model (no behaviour change)."""
        ...

    def complete(self, prompt: str, *, max_tokens: int, cache_prefix: str | None = None,
                 tier: str = "default", label: str = "") -> str:
        """Synchronous single-shot completion (engine text path). ``cache_prefix`` is an optional
        stable prefix a provider MAY prompt-cache (Anthropic ephemeral cache); ``None`` = no caching,
        identical to a plain completion. ``tier="fast"`` MAY route to a cheaper model (see
        ``llm_agent_model``). ``label`` names the calling stage for the token meter. Providers that
        can't cache / have no fast tier / don't meter ignore these."""
        ...
