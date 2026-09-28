"""`LiteLlmProvider` — a generic, env-driven LiteLlm backend so any LLM can be plugged in locally.

The Vertex provider hard-wires Claude-on-Vertex (needs GCP). This one wraps LiteLlm's model routing
directly, so a docker-compose / local run points at whatever endpoint LiteLlm speaks:

  * Anthropic direct : LITELLM_MODEL=anthropic/claude-sonnet-4-5   ANTHROPIC_API_KEY=sk-ant-...
  * Ollama (local)   : LITELLM_MODEL=ollama/llama3   LITELLM_API_BASE=http://host.docker.internal:11434
  * OpenAI-compatible: LITELLM_MODEL=openai/<served-name>   LITELLM_API_BASE=http://host.docker.internal:1234/v1
                       LITELLM_API_KEY=sk-local   (LM Studio / vLLM / llama.cpp / LocalAI)

Select it with TESTAGENT_MODEL_BACKEND=litellm. `drop_params=True` lets LiteLlm silently drop params a
local server doesn't support (thinking/cache_control/etc.), which is what makes plugging arbitrary
local models work without per-server special-casing.
"""

from __future__ import annotations

import os

_ENV_MODEL = "LITELLM_MODEL"


def _env(key: str) -> str | None:
    v = os.environ.get(key)
    return v.strip() or None if v else None


def _extra_args() -> dict:
    """api_base / api_key when set — omitted (not passed as None) so LiteLlm keeps its own defaults."""
    extra: dict = {"drop_params": True}
    if base := _env("LITELLM_API_BASE"):
        extra["api_base"] = base
    if key := _env("LITELLM_API_KEY"):
        extra["api_key"] = key
    return extra


class LiteLlmProvider:
    name = "litellm"

    def is_configured(self) -> bool:
        return _env(_ENV_MODEL) is not None

    @staticmethod
    def _model(tier: str) -> str:
        model = _env(_ENV_MODEL)
        if model is None:
            raise RuntimeError(f"LiteLlmProvider is not configured ({_ENV_MODEL} unset)")
        return (_env("LITELLM_MODEL_FAST") or model) if tier == "fast" else model

    def llm_agent_model(self, *, max_tokens: int | None = None, tier: str = "default"):
        if not self.is_configured():
            return None
        from google.adk.models.lite_llm import LiteLlm

        from common.adk.config import get_config

        return LiteLlm(model=self._model(tier),
                       max_tokens=max_tokens or get_config().default_max_tokens, **_extra_args())

    def complete(self, prompt: str, *, max_tokens: int, cache_prefix: str | None = None,
                 tier: str = "default", label: str = "") -> str:
        # cache_prefix is a no-op here (prompt caching is provider-specific); prepend so the text still
        # reaches the model when a caller passes a stable pack prefix.
        import litellm

        content = f"{cache_prefix}\n\n{prompt}" if cache_prefix else prompt
        resp = litellm.completion(model=self._model(tier),
                                  messages=[{"role": "user", "content": content}],
                                  max_tokens=max_tokens, **_extra_args())
        return resp.choices[0].message.content or ""
