"""Model-provider registry — the single place a new model backend is registered (C1/D10)."""

from __future__ import annotations

from common.adk.config import get_config
from common.adk.providers.base import ModelProvider
from common.adk.providers.decision import DecisionProvider, Verdict
from common.adk.providers.jev import JevProvider
from common.adk.providers.vertex_claude import VertexClaudeProvider

_REGISTRY: dict[str, type] = {
    "claude": VertexClaudeProvider,
}

_DECISION_REGISTRY: dict[str, type] = {
    "jev": JevProvider,
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


def get_decision_provider() -> DecisionProvider | None:
    """The configured `DecisionProvider` (a fresh instance), or `None` when `TPD_DECISION_BACKEND` is
    unset/unknown (OFF → callers keep their LLM path). The sibling of `get_provider`, but OFF by default
    and returning None rather than raising, so the whole feature is strictly additive (I8-safe: touches
    only the opt-in judged / always-on assured tiers, never the deterministic scorers)."""
    cls = _DECISION_REGISTRY.get(get_config().decision_backend.strip().lower())
    return cls() if cls else None


__all__ = [
    "DecisionProvider",
    "ModelProvider",
    "Verdict",
    "VertexClaudeProvider",
    "get_decision_provider",
    "get_provider",
]
