"""A2A task-store factory shared by both agent servers.

`DefaultRequestHandler` persists A2A `Task` objects via a `TaskStore`. The default
`InMemoryTaskStore` loses every task when the Cloud Run instance restarts / scales to
zero / gets a new revision, and cannot be shared across instances. `build_task_store()`
returns a durable Postgres-backed `DatabaseTaskStore` (a2a-sdk) when a DB is configured,
and otherwise falls back to in-memory — so local dev and tests need no DB.

The connection logic (env resolution + Cloud SQL Python Connector engine) lives in
`common.db`, so the task store and the pgvector memory store share ONE engine/pool and
dial the instance the same way. `DatabaseTaskStore` creates the `tasks` table lazily on
first use, so no startup await.
"""

from __future__ import annotations

from a2a.server.tasks import InMemoryTaskStore, TaskStore

from common.db import get_engine
from common.monitoring import get_logger

log = get_logger("taskstore")


def build_task_store() -> TaskStore:
    """Return a durable DatabaseTaskStore when a DB is configured, else InMemoryTaskStore."""
    engine = get_engine()
    if engine is None:
        log.info("task store: in-memory (no DB configured)")
        return InMemoryTaskStore()

    try:
        from a2a.server.tasks import DatabaseTaskStore
    except ImportError:
        # Missing driver shouldn't silently drop us to a store that loses tasks.
        log.error("DB configured but a2a-sdk[postgresql] is not installed — install it (SQLAlchemy + asyncpg)")
        raise

    log.info("task store: Postgres via DatabaseTaskStore (%s)", engine.url.render_as_string(hide_password=True))
    return DatabaseTaskStore(engine, create_table=True)
