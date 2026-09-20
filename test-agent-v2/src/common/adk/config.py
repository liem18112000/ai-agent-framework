"""Central config (E2) — pydantic-settings, the canonical ADK-sample idiom."""

from __future__ import annotations

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TESTAGENT_", env_file=".env", extra="ignore")
    model_backend: str = "claude"
    default_max_tokens: int = 128000  # the model's output ceiling; a lower cap truncates mid-JSON


def get_config() -> Config:
    """A fresh Config (reads current env each call)."""
    return Config()


def turbo_on() -> bool:
    """True when the Turbo perf profile is on (env `TESTAGENT_TURBO`). Read directly at each aggressive
    gate (assured iters, per-round critique, refine passes) to pick a faster default — an explicit
    per-flag env still overrides. One boolean, no profile enum / mapping layer (see PLAN §Mode B)."""
    return os.environ.get("TESTAGENT_TURBO", "").strip().lower() in ("1", "true", "yes", "on")
