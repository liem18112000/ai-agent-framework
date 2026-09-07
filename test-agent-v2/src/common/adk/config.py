"""Central config (E2) — pydantic-settings, the canonical ADK-sample idiom.

One switch for the model backend — **Claude-via-LiteLlm (default)** or **Gemini-native** — plus shared
knobs. Env-prefixed `TESTAGENT_` so it never collides with the engine's `VERTEX_*` / `GCS_*` env; the
Claude path still resolves its Vertex project/location from `VERTEX_PROJECT`/`VERTEX_LOCATION` via
`common.llm.vertex.vertex_config` (unchanged). Additive and non-breaking: default behavior = today.
"""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TESTAGENT_", env_file=".env", extra="ignore")

    model_backend: Literal["claude", "gemini"] = "claude"
    gemini_model: str = "gemini-2.5-flash"
    default_max_tokens: int = 6000


def get_config() -> Config:
    """A fresh Config (reads current env each call)."""
    return Config()
