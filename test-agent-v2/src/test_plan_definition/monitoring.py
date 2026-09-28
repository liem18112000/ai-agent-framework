"""Toggleable logging for test_plan_definition (env `TPD_LOG`, level `TPD_LOG_LEVEL`)."""

from __future__ import annotations

from common.monitoring import LoggingToggle

_toggle = LoggingToggle("test_plan_definition", "TPD")
configure = _toggle.configure
enable = _toggle.enable
disable = _toggle.disable
get_logger = _toggle.get_logger
