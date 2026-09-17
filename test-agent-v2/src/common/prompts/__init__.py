"""Prompt store — prompts as addressable, versioned data instead of text compiled into the image.

    from common.prompts import store_for
    store = store_for(DEFAULTS)          # Pg-backed when a DB is configured, else the Python bodies
    await store.refresh()                # once per run: loads + PINS the snapshot (P4)
    store.get("tpd.scenarios").render({"kinds": "...", "scope_block": "..."})

The port is in ``port``, the implementations in ``stores``, and the ADK seam in ``adk`` — importing
this package does NOT import ADK or SQLAlchemy.
"""

from __future__ import annotations

from collections.abc import Mapping

from common.prompts.port import (
    NONE,
    PromptNotFound,
    PromptStore,
    PromptTemplate,
    declared_vars,
)
from common.prompts.stores import PgPromptStore, PyPromptStore, validate

__all__ = [
    "NONE",
    "PgPromptStore",
    "PromptNotFound",
    "PromptStore",
    "PromptTemplate",
    "PyPromptStore",
    "declared_vars",
    "reset_store_cache",
    "store_for",
    "validate",
]

_cache: dict[int, PromptStore] = {}


def store_for(defaults: Mapping[str, PromptTemplate]) -> PromptStore:
    """The store serving ``defaults`` — Cloud SQL-backed when a DB is configured, else the defaults.

    Cached per defaults-mapping so every caller in a process shares one snapshot (and therefore one
    pinned version set). No import-time side effects: the caller owns its defaults and passes them in."""
    cached = _cache.get(id(defaults))
    if cached is not None:
        return cached
    from common.db import get_engine

    py = PyPromptStore(defaults)
    store: PromptStore = PgPromptStore(py) if get_engine() is not None else py
    _cache[id(defaults)] = store
    return store


def reset_store_cache() -> None:
    """Drop the cached stores (tests only — lets a test flip DB env and rebuild)."""
    _cache.clear()
