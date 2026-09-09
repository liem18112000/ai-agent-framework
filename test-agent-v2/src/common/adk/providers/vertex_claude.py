"""`VertexClaudeProvider` — Claude Sonnet 5 on Vertex, the sole concrete `ModelProvider` (C1/D10)."""

from __future__ import annotations

from common.adk.config import get_config
from common.llm.vertex import agenerate as _vertex_agenerate
from common.llm.vertex import complete as _vertex_complete
from common.llm.vertex import vertex_config


class VertexClaudeProvider:
    name = "claude"

    def is_configured(self) -> bool:
        """True when VERTEX_* is set (project/location/model resolvable)."""
        return vertex_config() is not None

    def llm_agent_model(self, *, max_tokens: int | None = None):
        """A `LiteLlm` for Claude-on-Vertex, or `None` when VERTEX_* is unset (→ heuristic, I7)."""
        cfg = vertex_config()
        if cfg is None:
            return None
        project, location, model = cfg
        from google.adk.models.lite_llm import LiteLlm

        return LiteLlm(model=f"vertex_ai/{model}", vertex_project=project, vertex_location=location,
                       max_tokens=max_tokens or get_config().default_max_tokens, thinking={"type": "disabled"})

    def complete(self, prompt: str, *, max_tokens: int) -> str:
        project, location, model = self._require_config()
        return _vertex_complete(prompt, project=project, location=location, model=model, max_tokens=max_tokens)

    async def agenerate(self, prompt: str, *, max_tokens: int) -> str:
        project, location, model = self._require_config()
        return await _vertex_agenerate(prompt, project=project, location=location, model=model, max_tokens=max_tokens)

    @staticmethod
    def _require_config() -> tuple[str, str, str]:
        cfg = vertex_config()
        if cfg is None:
            raise RuntimeError("VertexClaudeProvider is not configured (VERTEX_* unset)")
        return cfg
