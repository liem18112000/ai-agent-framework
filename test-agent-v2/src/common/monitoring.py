"""Toggleable logging, shared by the engine and both agents."""

from __future__ import annotations

import logging
import os

_OFF = logging.CRITICAL + 1


def _truthy(v: str | None) -> bool:
    return str(v).lower() in ("1", "true", "yes", "on")


class LoggingToggle:
    """One toggleable logger namespace: children of `root`, gated by `<prefix>_LOG` env."""

    def __init__(self, root: str, env_prefix: str) -> None:
        self.root = root
        self._env = f"{env_prefix}_LOG"
        self._level_env = f"{env_prefix}_LOG_LEVEL"
        self._ready = False

    def configure(self, enabled: bool | None = None, level: str | None = None) -> None:
        """Apply the toggle. `enabled=None` reads env `<prefix>_LOG` (default off)."""
        if enabled is None:
            enabled = _truthy(os.environ.get(self._env))
        logger = logging.getLogger(self.root)
        logger.propagate = False
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S")
            )
            logger.addHandler(handler)
        chosen = (level or os.environ.get(self._level_env) or "INFO").upper()
        logger.setLevel(chosen if enabled else _OFF)
        self._ready = True

    def enable(self, level: str = "INFO") -> None:
        self.configure(enabled=True, level=level)

    def disable(self) -> None:
        self.configure(enabled=False)

    def get_logger(self, name: str) -> logging.Logger:
        if not self._ready:
            self.configure()
        return logging.getLogger(f"{self.root}.{name}")


_toggle = LoggingToggle("common", "COMMON")
configure = _toggle.configure
enable = _toggle.enable
disable = _toggle.disable
get_logger = _toggle.get_logger
