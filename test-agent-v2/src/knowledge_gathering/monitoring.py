"""Toggleable logging for knowledge_gathering (env `KGA_LOG`, level `KGA_LOG_LEVEL`)."""

from __future__ import annotations

from common.monitoring import LoggingToggle

_toggle = LoggingToggle("knowledge_gathering", "KGA")
configure = _toggle.configure
enable = _toggle.enable
disable = _toggle.disable
get_logger = _toggle.get_logger
