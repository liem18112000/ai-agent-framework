"""`build_vector_store()` — select the VectorStore backend from env (VECTOR_BACKEND)."""

from __future__ import annotations

import os

from common.memory.vector_store import VectorStore


def build_vector_store() -> VectorStore | None:
    """Select by VECTOR_BACKEND: `pgvector` (default) → the shared Cloud SQL pgvector store, exactly as
    `common.memory.pg.build_store()` (so `None` when no DB is configured, unchanged) | `memory` → a
    pure-Python `InMemoryVectorStore` (no DB, no network)."""
    backend = os.environ.get("VECTOR_BACKEND", "pgvector").lower()
    if backend == "memory":
        from common.memory.vector_memory import InMemoryVectorStore

        return InMemoryVectorStore()
    if backend in ("pgvector", "pg", "postgres"):
        from common.memory.pg import build_store

        return build_store()
    raise ValueError(f"unknown VECTOR_BACKEND: {backend!r}")
