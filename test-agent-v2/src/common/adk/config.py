"""Central config (E2) — pydantic-settings, the canonical ADK-sample idiom.

`model_backend` selects a registered `ModelProvider` (C1/D10) — default `"claude"`
(`VertexClaudeProvider`, the sole impl). It's an open string validated against the provider registry
(`common/adk/providers`), so a future backend is a one-line registry entry, not a config change.
Env-prefixed `TESTAGENT_` so it never collides with the engine's `VERTEX_*` / `GCS_*` env; the Claude
provider resolves its Vertex project/location from `VERTEX_PROJECT`/`VERTEX_LOCATION` via
`common.llm.vertex.vertex_config` (unchanged).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TESTAGENT_", env_file=".env", extra="ignore")
    model_backend: str = "claude"  # a key in common/adk/providers._REGISTRY
    default_max_tokens: int = 6000


def get_config() -> Config:
    """A fresh Config (reads current env each call)."""
    return Config()
