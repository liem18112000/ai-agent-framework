"""A2A task-store factory shared by both agent servers."""

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
        log.error("DB configured but a2a-sdk[postgresql] is not installed — install it (SQLAlchemy + asyncpg)")
        raise

    log.info("task store: Postgres via DatabaseTaskStore (%s)", engine.url.render_as_string(hide_password=True))
    return DatabaseTaskStore(engine, create_table=True)
