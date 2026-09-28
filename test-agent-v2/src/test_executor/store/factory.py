"""The process-wide run-ledger factory: Postgres on the shared engine, or the in-memory fallback offline."""

from __future__ import annotations

from common.monitoring import get_logger
from test_executor.store.memory import InMemoryExecStore
from test_executor.store.sql import ExecStore

log = get_logger("exec.store")

_STORE = None


def build_store():
    """The process-wide run ledger: Postgres on the shared engine, or the in-memory fallback offline.
    Memoized so the in-memory store keeps state across A2A turns (matches common.memory get_memory_store)."""
    global _STORE
    if _STORE is None:
        from common.db import get_engine

        engine = get_engine()
        _STORE = ExecStore(engine) if engine is not None else InMemoryExecStore()
        log.info("exec store: %s", type(_STORE).__name__)
    return _STORE
