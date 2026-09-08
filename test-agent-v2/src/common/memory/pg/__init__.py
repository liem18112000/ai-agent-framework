"""pgvector recall tier (two-tier-memory proposal). GCS stays the record; this is the query view."""

from __future__ import annotations

from common.memory.pg.store import PgMemoryStore

__all__ = ["PgMemoryStore", "build_store"]


def build_store():
    """A PgMemoryStore on the shared Cloud SQL engine, or None when no DB is configured."""
    from common.db import get_engine

    engine = get_engine()
    return PgMemoryStore(engine) if engine is not None else None
