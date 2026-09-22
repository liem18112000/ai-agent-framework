"""Monitoring toggle: on/off controls whether knowledge_gathering loggers emit."""

from __future__ import annotations

import logging

from knowledge_gathering.monitoring import configure, disable, enable, get_logger


def _capture():
    records: list[str] = []

    class H(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    logging.getLogger("knowledge_gathering").addHandler(H())
    return records


def test_disabled_silences_all_levels():
    configure(enabled=False)
    kga = logging.getLogger("knowledge_gathering")
    assert not kga.isEnabledFor(logging.INFO)
    assert not kga.isEnabledFor(logging.CRITICAL)


def test_enabled_emits():
    enable(level="DEBUG")
    records = _capture()
    get_logger("loop").info("hello %d", 7)
    assert "hello 7" in records


def test_toggle_off_after_on():
    enable()
    records = _capture()
    disable()
    get_logger("loop").info("should not appear")
    assert "should not appear" not in records
