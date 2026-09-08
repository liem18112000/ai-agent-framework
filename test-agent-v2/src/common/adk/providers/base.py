"""`ModelProvider` — the one documented extension point for "which model, reached how" (C1/D10, I8).

A provider abstracts model access behind a small interface. `VertexClaudeProvider` is the sole
concrete impl today (Claude-on-Vertex); a future `LocalClaudeProvider` (e.g. `ANTHROPIC_BASE_URL` → a
local endpoint) becomes a one-line registry entry in `providers/__init__.py` with nothing else changed.

Acyclic import rule: `common/adk/*` may import `common/llm/*`, never the reverse.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ModelProvider(Protocol):
    """Model access for the ADK layer. All model construction (LiteLlm / google.adk.models) lives in
    concrete providers only — that is invariant I8."""

    name: str

    def is_configured(self) -> bool:
        """True when the provider's transport is configured (replaces the raw `vertex_config()` gate,
        I7). False ⇒ the engine takes its deterministic heuristic path."""
        ...

    def llm_agent_model(self, *, max_tokens: int | None = None):
        """The model object for an ADK `LlmAgent` (a `LiteLlm` for Claude-on-Vertex), or `None` when
        the provider is unconfigured (→ heuristic fallback, I7)."""
        ...

    def complete(self, prompt: str, *, max_tokens: int) -> str:
        """Synchronous single-shot completion (engine text path; optional to route now — Option A)."""
        ...

    async def agenerate(self, prompt: str, *, max_tokens: int) -> str:
        """Async single-shot completion (engine text path; optional to route now — Option A)."""
        ...
