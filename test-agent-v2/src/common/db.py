"""Shared async SQLAlchemy engine for Cloud SQL — ONE pool for the A2A task store, the ADK sessions,
the pgvector memory tier and the executor's run ledger — plus `SchemaOnce`, the base every store on
that engine uses to apply its own DDL exactly once per process.
"""

from __future__ import annotations

import os

from common.env import env_int
from common.monitoring import get_logger

log = get_logger("db")

_engine = None
_resolved = False


def _db_config() -> dict | None:
    """Resolve DB connection settings from env into a tagged config dict, or None."""
    direct = os.environ.get("TASK_DB_URL")
    if direct:
        return {"kind": "url", "url": direct}
    conn, host = os.environ.get("DB_INSTANCE_CONNECTION_NAME"), os.environ.get("DB_HOST")
    if not (conn or host):
        return None
    user, password, name = os.environ.get("DB_USER"), os.environ.get("DB_PASSWORD"), os.environ.get("DB_NAME")
    missing = [k for k, v in (("DB_USER", user), ("DB_PASSWORD", password), ("DB_NAME", name)) if not v]
    if missing:
        log.warning("DB target set but %s missing — treating as no-DB (in-memory / gcs)", ", ".join(missing))
        return None
    if conn:
        return {"kind": "connector", "instance": conn, "user": user, "password": password, "database": name, "private_ip": os.environ.get("DB_USE_PRIVATE_IP", "").lower() in ("1", "true", "yes")}
    return {"kind": "tcp", "username": user, "password": password, "database": name, "host": host, "port": env_int("DB_PORT", 5432)}


def _connector_engine(cfg: dict):
    """Async SQLAlchemy engine that dials Cloud SQL via the Python Connector (no unix socket)."""
    from google.cloud.sql.connector import IPTypes, create_async_connector
    from sqlalchemy.ext.asyncio import create_async_engine

    ip_type = IPTypes.PRIVATE if cfg["private_ip"] else IPTypes.PUBLIC
    state: dict = {"connector": None}

    async def getconn():
        if state["connector"] is None:
            state["connector"] = await create_async_connector()
        return await state["connector"].connect_async(
            cfg["instance"], "asyncpg", user=cfg["user"], password=cfg["password"], db=cfg["database"], ip_type=ip_type
        )

    return create_async_engine("postgresql+asyncpg://", async_creator=getconn, pool_pre_ping=True)


def _build_engine(cfg: dict):
    """Create the async engine for a resolved config (connector / url / tcp)."""
    from sqlalchemy import URL
    from sqlalchemy.ext.asyncio import create_async_engine

    if cfg["kind"] == "connector":
        return _connector_engine(cfg)
    if cfg["kind"] == "url":
        return create_async_engine(cfg["url"], pool_pre_ping=True)
    kwargs = {k: cfg[k] for k in ("username", "password", "database", "host", "port")}
    return create_async_engine(URL.create("postgresql+asyncpg", **kwargs), pool_pre_ping=True)


def get_engine():
    """The shared async SQLAlchemy engine, or None when no DB is configured."""
    global _engine, _resolved
    if not _resolved:
        cfg = _db_config()
        if cfg is None:
            _engine = None
        else:
            try:
                _engine = _build_engine(cfg)
            except ImportError:
                log.error("DB configured but SQLAlchemy/asyncpg/cloud-sql-connector not installed — install them")
                raise
            log.info("db: engine ready (%s)", _engine.url.render_as_string(hide_password=True))
        _resolved = True
    return _engine


def reset_engine_cache() -> None:
    """Drop the cached engine (tests only — lets a test flip env and rebuild)."""
    global _engine, _resolved
    _engine, _resolved = None, False


class SchemaOnce:
    """Base for a store that owns tables on the shared engine: applies `SCHEMA_SQL` once per process.

    Subclass and set `SCHEMA_SQL` to idempotent `CREATE … IF NOT EXISTS` statements separated by `;`,
    then `await self._ensure()` at the top of each public method.

    The lock is the point. Two concurrent first callers both racing the CREATE EXTENSION/INDEX raise
    `tuple concurrently updated`, and the store then degrades silently (MEM-02). This lived as a
    byte-identical copy in `memory/pg/store.py` and `test_executor/store/sql.py` — two copies of a
    race fix is one copy too many, since a correction to either is invisible in the other."""

    SCHEMA_SQL = ""

    def __init__(self, engine) -> None:
        self._engine = engine
        self._ready = False
        self._lock = None

    async def _ensure(self) -> None:
        if self._ready:
            return
        import asyncio

        from sqlalchemy import text
        if self._lock is None:  # no await before assignment → safe under cooperative asyncio
            self._lock = asyncio.Lock()
        async with self._lock:
            if self._ready:
                return
            async with self._engine.begin() as conn:
                for stmt in (s.strip() for s in self.SCHEMA_SQL.split(";") if s.strip()):
                    await conn.execute(text(stmt))
            self._ready = True
