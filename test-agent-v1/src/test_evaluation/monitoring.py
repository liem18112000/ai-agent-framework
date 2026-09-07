"""Toggleable logging for test_evaluation (env `TEV_LOG`, level `TEV_LOG_LEVEL`).

A thin instance of common.monitoring.LoggingToggle over the "test_evaluation" logger root, so it
switches independently of the KGA/TPD/COMMON namespaces. `get_logger("engine")` ->
logging.getLogger("test_evaluation.engine").
"""

from __future__ import annotations

from common.monitoring import LoggingToggle

_toggle = LoggingToggle("test_evaluation", "TEV")
configure = _toggle.configure
enable = _toggle.enable
disable = _toggle.disable
get_logger = _toggle.get_logger
