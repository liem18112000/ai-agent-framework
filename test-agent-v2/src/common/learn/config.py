"""Self-learning feature flags (default OFF). `agent` = "KGA" | "TPD"."""

from __future__ import annotations

import os


def _on(var: str) -> bool:
    return os.environ.get(var, "").lower() in ("1", "true", "yes", "on")


def capture_enabled(agent: str) -> bool:
    return _on(f"{agent}_CAPTURE_LESSONS")


def recall_enabled(agent: str) -> bool:
    return _on(f"{agent}_RECALL_LESSONS")
