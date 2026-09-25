"""Numeric environment-variable reads that degrade instead of crashing.

The codebase reads ~30 numeric settings straight out of the environment. Six wrapped the parse in a
try/except; the rest did not — so a single typo in a deployed env var (`EXEC_CHUNK=5s`, an empty
`DB_PORT`) raised `ValueError`, and at the module-import sites that is a container crash-loop rather
than one bad setting. These helpers make the whole surface behave the same way: an unparseable value
logs and falls back to the default, because a wrong number should degrade one knob, not the process.
"""

from __future__ import annotations

import os

from common.monitoring import get_logger

log = get_logger("common.env")


def _num(name: str, default, cast):
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return cast(raw)
    except (TypeError, ValueError):
        log.warning("env %s=%r is not a valid %s — using %r", name, raw, cast.__name__, default)
        return default


def env_int(name: str, default: int) -> int:
    """`name` as an int, or `default` when unset, blank, or unparseable."""
    return _num(name, default, int)


def env_float(name: str, default: float) -> float:
    """`name` as a float, or `default` when unset, blank, or unparseable."""
    return _num(name, default, float)
