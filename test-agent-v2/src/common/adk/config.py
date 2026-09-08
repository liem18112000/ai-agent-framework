"""Central config (E2) — pydantic-settings, the canonical ADK-sample idiom."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TESTAGENT_", env_file=".env", extra="ignore")
    model_backend: str = "claude"
    default_max_tokens: int = 6000


def get_config() -> Config:
    """A fresh Config (reads current env each call)."""
    return Config()
