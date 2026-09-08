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

    def llm_agent_model(self, *, max_tokens: int | None = None):
        """The model object for an ADK `LlmAgent` (a `LiteLlm` for Claude-on-Vertex), or `None` when"""
        ...

    def complete(self, prompt: str, *, max_tokens: int) -> str:
        """Synchronous single-shot completion (engine text path; optional to route now — Option A)."""
        ...

    async def agenerate(self, prompt: str, *, max_tokens: int) -> str:
        """Async single-shot completion (engine text path; optional to route now — Option A)."""
        ...
