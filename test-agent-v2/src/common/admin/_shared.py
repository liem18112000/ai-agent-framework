"""Shared helpers for the admin package — blob-store access, formatting, run enumeration, DB reflection.

Imported by the per-feature modules (`runs`, `memory_view`, `backup`, `wipe`). Depends only on the
`MemoryBank` blob layer and the shared async SQLAlchemy engine; no feature module imports another.
"""

from __future__ import annotations

from common.memory.bank import ROOT, _slug
from common.monitoring import get_logger

__all__ = [
    "ROOT",
    "_BACKUPS_ROOT",
    "_REFINE_PREFIX",
    "_RUNS_PREFIX",
    "_first_table_count",
    "_kinds_str",
    "_run_contexts",
    "_slug",
    "_store",
    "_table_names",
    "log",
]

log = get_logger("admin")

_REFINE_PREFIX = f"{ROOT}/refine/"
_RUNS_PREFIX = f"{ROOT}/runs/"
_BACKUPS_ROOT = "memory-backups"


def _store(bank):
    """The ObjectStore behind a MemoryBank — admin needs list/delete/copy at the blob layer (§3)."""
    return bank._bucket


def _kinds_str(kinds: dict) -> str:
    return ", ".join(f"{k}:{v}" for k, v in sorted(kinds.items())) or "empty"


def _run_contexts(bank) -> list[str]:
    """The known runs — one dir under memory/refine/ per context (computed on read, no sidecar index)."""
    ctxs: set[str] = set()
    for blob in _store(bank).iter_blobs(_REFINE_PREFIX):
        top = blob.name[len(_REFINE_PREFIX):].split("/", 1)[0]
        if top and top != "_sessions":
            ctxs.add(top)
    return sorted(ctxs)


# --- shared DB helpers (async engine) --------------------------------------------------------------

async def _table_names(engine) -> list[str]:
    """Reflected table names on the shared engine (run over a sync connection via run_sync)."""
    from sqlalchemy import inspect

    async with engine.connect() as conn:
        return await conn.run_sync(lambda c: inspect(c).get_table_names())


async def _first_table_count(engine, candidates: tuple[str, ...]) -> int | None:
    """Row count of the first of `candidates` that exists, or None when none do."""
    from sqlalchemy import text

    names = set(await _table_names(engine))
    table = next((c for c in candidates if c in names), None)
    if table is None:
        return None
    async with engine.connect() as conn:
        return (await conn.execute(text(f'SELECT count(*) FROM "{table}"'))).scalar() or 0
