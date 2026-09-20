"""pgvector recall tier (two-tier-memory proposal). GCS stays the record; this is the query view."""

from __future__ import annotations

from common.memory.pg.store import PgMemoryStore

__all__ = ["PgMemoryStore", "build_store"]

# MEM-02: memoize the store per process (keyed on the shared engine, as get_engine is cached) so
# _ensure()'s _ready short-circuit holds across requests and SCHEMA_SQL is applied once, not per call.
_store = None
_store_engine = None


def build_store():
    """A PgMemoryStore on the shared Cloud SQL engine (memoized per process), or None when no DB is configured."""
    global _store, _store_engine
    from common.db import get_engine

    engine = get_engine()
    if engine is None:
        return None
    if _store is None or _store_engine is not engine:
        _store, _store_engine = PgMemoryStore(engine), engine
    return _store
