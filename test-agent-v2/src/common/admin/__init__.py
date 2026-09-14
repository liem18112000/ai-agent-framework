"""Memory & history ADMIN handlers — an operator utility, NOT part of the testing pipeline.

Pure functions over a `MemoryBank` (GCS/in-memory) and the shared async SQLAlchemy `engine`:
run history (F1), memory introspection (F2), backup-as-version (F4), and a guarded wipe-all (F3).
They only READ, RESET, or COPY state that already exists — never a new source of truth. Framework-
neutral and offline-testable against `InMemoryObjectStore` + a None/fake engine.

Split into one module per feature (`runs` / `memory_view` / `backup` / `wipe`) over shared helpers
(`_shared`); this package re-exports the public API so callers keep `from common import admin`.

`restore_backup`, a `scope=` on wipe, and `format=` toggles are DEFERRED (see the plan's scope trim).
"""

from __future__ import annotations

from common.admin.backup import backup_memory, list_backups
from common.admin.memory_view import view_memory
from common.admin.runs import RunDetail, RunSummary, get_run, list_runs
from common.admin.wipe import wipe_all, wipe_required_token

__all__ = [
    "RunDetail",
    "RunSummary",
    "backup_memory",
    "get_run",
    "list_backups",
    "list_runs",
    "view_memory",
    "wipe_all",
    "wipe_required_token",
]
