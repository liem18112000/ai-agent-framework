"""Toggleable logging for test_evaluation (env `TEV_LOG`, level `TEV_LOG_LEVEL`)."""

from __future__ import annotations

from common.monitoring import LoggingToggle

_toggle = LoggingToggle("test_evaluation", "TEV")
configure = _toggle.configure
enable = _toggle.enable
disable = _toggle.disable
get_logger = _toggle.get_logger
