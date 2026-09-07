"""Toggleable logging for knowledge_gathering (env `KGA_LOG`, level `KGA_LOG_LEVEL`).

A thin instance of common.monitoring.LoggingToggle over the "knowledge_gathering" logger root,
so it switches on/off independently of the other namespaces. `get_logger("loop")` ->
logging.getLogger("knowledge_gathering.loop").
"""

from __future__ import annotations

from common.monitoring import LoggingToggle

_toggle = LoggingToggle("knowledge_gathering", "KGA")
configure = _toggle.configure
enable = _toggle.enable
disable = _toggle.disable
get_logger = _toggle.get_logger
