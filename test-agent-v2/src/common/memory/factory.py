"""`build_bank()` — the markdown memory bank over the configured ObjectStore, framework-neutral."""

from __future__ import annotations


def build_bank():
    """The memory bank over the configured ObjectStore (STORE_BACKEND; GCS by default, from env)."""
    from common.memory import MemoryBank
    from common.memory.pg.project import index_on_write
    from common.store import build_object_store

    return MemoryBank(build_object_store(), on_write=index_on_write)
