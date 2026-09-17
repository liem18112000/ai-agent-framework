"""`VertexClaudeProvider` — Claude Sonnet 5 on Vertex, the sole concrete `ModelProvider` (C1/D10)."""

from __future__ import annotations

import os

from common.adk.config import get_config
from common.llm.vertex import agenerate as _vertex_agenerate
from common.llm.vertex import complete as _vertex_complete
from common.llm.vertex import vertex_config


class VertexClaudeProvider:
    name = "claude"

    def is_configured(self) -> bool:
        """True when VERTEX_* is set (project/location/model resolvable)."""
        return vertex_config() is not None

    @staticmethod
    def _tier_model(model: str, tier: str) -> str:
        """The model id for a tier: ``fast`` → ``VERTEX_MODEL_FAST`` when set (a cheaper model for
        classification/judging), else the default model — so the fast tier is inert until an operator
        sets that env (zero behaviour change by default). Any other tier → the default model."""
        if tier == "fast":
            return os.environ.get("VERTEX_MODEL_FAST") or model
        return model

    def llm_agent_model(self, *, max_tokens: int | None = None, tier: str = "default"):
        """A `LiteLlm` for Claude-on-Vertex, or `None` when VERTEX_* is unset (→ heuristic, I7)."""
        cfg = vertex_config()
        if cfg is None:
            return None
        project, location, model = cfg
        model = self._tier_model(model, tier)
        from google.adk.models.lite_llm import LiteLlm

        extra = {}
        # Anthropic prompt caching on the shared system message (the cached context pack, see
        # build_generator_agent). LiteLlm forwards this to litellm.acompletion → cache_control on the
        # system block, so the pack is reused across generators + assured reflect-rounds. Escape hatch:
        # TPD_ADK_CACHE=0 (unverifiable offline; disable if the installed litellm rejects the param).
        if os.environ.get("TPD_ADK_CACHE", "1") != "0":
            extra["cache_control_injection_points"] = [{"location": "message", "role": "system"}]
        return LiteLlm(model=f"vertex_ai/{model}", vertex_project=project, vertex_location=location,
                       max_tokens=max_tokens or get_config().default_max_tokens,
                       thinking={"type": "disabled"}, **extra)

    def complete(self, prompt: str, *, max_tokens: int, cache_prefix: str | None = None,
                 tier: str = "default") -> str:
        project, location, model = self._require_config()
        return _vertex_complete(prompt, project=project, location=location,
                                model=self._tier_model(model, tier),
                                max_tokens=max_tokens, cache_prefix=cache_prefix)

    async def agenerate(self, prompt: str, *, max_tokens: int) -> str:
        project, location, model = self._require_config()
        return await _vertex_agenerate(prompt, project=project, location=location, model=model, max_tokens=max_tokens)

    @staticmethod
    def _require_config() -> tuple[str, str, str]:
        cfg = vertex_config()
        if cfg is None:
            raise RuntimeError("VertexClaudeProvider is not configured (VERTEX_* unset)")
        return cfg
