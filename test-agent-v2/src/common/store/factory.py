"""`build_object_store()` — select the ObjectStore backend from env (STORE_BACKEND)."""

from __future__ import annotations

import os

from common.store.object_store import ObjectStore


def build_object_store() -> ObjectStore:
    """Select by STORE_BACKEND: `gcs` (default) | `memory`."""
    backend = os.environ.get("STORE_BACKEND", "gcs").lower()
    if backend == "memory":
        from common.store.memory import InMemoryObjectStore

        return InMemoryObjectStore()
    if backend == "gcs":
        from common.store.gcs import GcsObjectStore

        return GcsObjectStore.from_env()
    raise ValueError(f"unknown STORE_BACKEND: {backend!r}")
