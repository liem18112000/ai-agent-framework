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
from common.admin.memory_graph import memory_graph_html
from common.admin.memory_view import view_memory
from common.admin.runs import (
    RunDetail,
    RunSummary,
    compare_runs,
    get_artifacts,
    get_run,
    list_runs,
    record_artifact,
)
from common.admin.tokens import (
    estimate_usage,
    persist_usage,
    record_token_lesson,
    token_by_agent,
    token_usage,
)
from common.admin.wipe import forget_memory, wipe_all, wipe_required_token

__all__ = [
    "RunDetail",
    "RunSummary",
    "backup_memory",
    "compare_runs",
    "estimate_usage",
    "forget_memory",
    "get_artifacts",
    "get_run",
    "list_backups",
    "list_runs",
    "memory_graph_html",
    "persist_usage",
    "record_artifact",
    "record_token_lesson",
    "token_by_agent",
    "token_usage",
    "view_memory",
    "wipe_all",
    "wipe_required_token",
]
