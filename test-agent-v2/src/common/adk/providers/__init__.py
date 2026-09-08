"""Model-provider registry — the single place a new model backend is registered (C1/D10).

`get_provider()` maps `Config.model_backend` (default `"claude"`) to a concrete `ModelProvider`.
Add a future backend by adding one registry entry (e.g. `"local": LocalClaudeProvider`) — nothing
else in the codebase changes. An unknown backend name raises a clear `KeyError`.
"""

from __future__ import annotations

from common.adk.config import get_config
from common.adk.providers.base import ModelProvider
from common.adk.providers.vertex_claude import VertexClaudeProvider

_REGISTRY: dict[str, type] = {
    "claude": VertexClaudeProvider,
}


def get_provider() -> ModelProvider:
    """The configured `ModelProvider` (a fresh instance). Default `"claude"`; unknown → `KeyError`."""
    backend = get_config().model_backend
    try:
        return _REGISTRY[backend]()
    except KeyError:
        raise KeyError(
            f"unknown model_backend {backend!r}; registered: {sorted(_REGISTRY)}"
        ) from None


__all__ = ["ModelProvider", "VertexClaudeProvider", "get_provider"]
