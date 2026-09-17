"""F3 — wipe-all (DESTRUCTIVE, guarded): clear the bank, pgvector, and the a2a/adk tables in one call."""

from __future__ import annotations

from common.admin._shared import ROOT, _table_names


def wipe_required_token() -> str:
    """The confirm token `wipe_all` demands: the GCS_BUCKET value, or literal 'WIPE' when unset."""
    import os

    return os.environ.get("GCS_BUCKET") or "WIPE"


#: The pgvector recall tier — rebuildable from the GCS bank via ``pg/backfill.py``.
_PGVECTOR_TABLES = ("memory_node", "memory_edge")

#: Per-run state a wipe is MEANT to clear. This is an ALLOWLIST, and deliberately so.
#:
#: It used to be "every table that is not pgvector", which made wipe_all a catch-all: any table added
#: to the shared database was silently in scope. That bit hard on 2026-09-17 — the wipe truncated
#: ``adk_internal_metadata``, removing ADK's ``schema_version`` row, and EVERY agent then failed with
#: "Schema version not found in adk_internal_metadata" on its next request (all five share one
#: DatabaseSessionService, so one row = total outage). It also destroyed the prompt store's
#: ``prompt_template`` / ``prompt_version`` rows, which are CONFIGURATION, not memory — wiping the
#: memory bank should never discard someone's edited prompts.
#:
#: Anything not listed here is reported as preserved rather than quietly truncated. Add a table here
#: only if a memory wipe genuinely should clear it.
_RUNTIME_TABLES = ("sessions", "events", "app_states", "user_states", "tasks")


async def wipe_all(bank, engine, confirm: str, *, required_token: str | None = None) -> str:
    """DESTRUCTIVE (F3): clear the memory bank, pgvector, and the A2A task + ADK session tables in one
    guarded call. Requires `confirm` == the required token (GCS_BUCKET, or 'WIPE' when unset).

    Never touches memory-backups/** — a backup survives a wipe on purpose. Idempotent: a second call
    reports zero. pgvector/task/session tables are TRUNCATEd (not dropped) so the schema survives."""
    required = required_token or wipe_required_token()
    if not confirm or confirm != required:
        return (f"REFUSED — wipe_all is destructive. Re-call with confirm={required!r} "
                f"(the exact token required to proceed).")

    report = ["# Wipe-all report"]

    # 1) memory bank — leaves memory-backups/** untouched (trailing-slash prefix excludes it).
    removed = bank.delete_prefix(f"{ROOT}/")
    report.append(f"- memory bank: {removed} blobs removed (memory-backups/** preserved)")

    # 2/3) pgvector + the a2a/adk tables on the shared engine.
    if engine is None:
        report.append("- pgvector: in-memory, nothing persisted")
        report.append("- task/session store: in-memory, nothing persisted")
        return "\n".join(report)

    from sqlalchemy import text

    names = await _table_names(engine)
    pg_tables = [t for t in _PGVECTOR_TABLES if t in names]
    other_tables = [t for t in _RUNTIME_TABLES if t in names]
    skipped = sorted(set(names) - set(pg_tables) - set(other_tables))
    async with engine.begin() as conn:
        pg_rows = await _truncate(conn, text, pg_tables)
        other_rows = await _truncate(conn, text, other_tables)
    report.append(f"- pgvector: {pg_rows} rows truncated ({', '.join(pg_tables) or 'no tables'})")
    report.append(f"- task/session store: {other_rows} rows truncated "
                  f"({', '.join(other_tables) or 'no tables'})")
    if skipped:
        report.append(f"- preserved (not memory/run data): {', '.join(skipped)}")
    return "\n".join(report)


async def _truncate(conn, text, tables: list[str]) -> int:
    """Count then TRUNCATE `tables` (CASCADE, one statement — FK-safe); return rows removed."""
    if not tables:
        return 0
    total = 0
    for t in tables:
        total += (await conn.execute(text(f'SELECT count(*) FROM "{t}"'))).scalar() or 0
    quoted = ", ".join(f'"{t}"' for t in tables)
    await conn.execute(text(f"TRUNCATE TABLE {quoted} CASCADE"))
    return total
