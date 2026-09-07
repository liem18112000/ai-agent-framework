"""pgvector recall tier (two-tier-memory proposal). GCS stays the record; this is the query view."""

from __future__ import annotations

from common.memory.pg.store import PgMemoryStore

__all__ = ["PgMemoryStore", "build_store"]


def build_store():
    """A PgMemoryStore on the shared Cloud SQL engine, or None when no DB is configured.

    None → the retrieval facade uses the GCS graph path. Independent of MEMORY_BACKEND so a
    caller can build the store once and let the facade decide per-call whether to use it.
    """
    from common.db import get_engine

    engine = get_engine()
    return PgMemoryStore(engine) if engine is not None else None
