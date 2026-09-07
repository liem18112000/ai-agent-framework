"""Shared async SQLAlchemy engine for Cloud SQL — ONE pool for the A2A task store AND the
pgvector memory store (M0 of the two-tier-memory proposal).

Extracted from `common.taskstore` so both dial the same instance the same way (Cloud SQL
Python Connector, IAM + TLS — NOT the /cloudsql socket, which never reaches a Cloud Run
sidecar; see the task-store notes). The engine is cached module-level and created eagerly
(cheap, synchronous — no connection is opened until first use, inside the running loop).

Config (env, set by terraform on Cloud Run; see deployments/cloudsql.tf):
  * TASK_DB_URL                  — full SQLAlchemy async URL; wins over everything else.
  * DB_INSTANCE_CONNECTION_NAME  — Cloud SQL "PROJECT:REGION:INSTANCE" via the Connector.
    Requires DB_USER, DB_PASSWORD, DB_NAME. Optional DB_USE_PRIVATE_IP=1 for private IP.
  * DB_HOST (+ DB_PORT)          — plain TCP (local docker-compose / a proxy). Same creds.
  * none of the above           — no DB → in-memory task store / gcs memory backend.
"""

from __future__ import annotations

import os

from common.monitoring import get_logger

log = get_logger("db")

_engine = None
_resolved = False


def _db_config() -> dict | None:
    """Resolve DB connection settings from env into a tagged config dict, or None.

    Returns one of:
      * {"kind": "url", "url": <str>}                             — TASK_DB_URL passthrough
      * {"kind": "connector", "instance", "user", ...}            — Cloud SQL Python Connector
      * {"kind": "tcp", "username", "password", "host", "port"}   — plain TCP
      * None                                                      — no DB configured
    """
    direct = os.environ.get("TASK_DB_URL")
    if direct:
        return {"kind": "url", "url": direct}

    conn = os.environ.get("DB_INSTANCE_CONNECTION_NAME")
    host = os.environ.get("DB_HOST")
    if not (conn or host):
        return None

    user = os.environ.get("DB_USER")
    password = os.environ.get("DB_PASSWORD")
    name = os.environ.get("DB_NAME")
    missing = [k for k, v in (("DB_USER", user), ("DB_PASSWORD", password), ("DB_NAME", name)) if not v]
    if missing:
        log.warning("DB target set but %s missing — treating as no-DB (in-memory / gcs)", ", ".join(missing))
        return None

    if conn:
        return {
            "kind": "connector",
            "instance": conn,
            "user": user,
            "password": password,
            "database": name,
            "private_ip": os.environ.get("DB_USE_PRIVATE_IP", "").lower() in ("1", "true", "yes"),
        }
    return {
        "kind": "tcp",
        "username": user,
        "password": password,
        "database": name,
        "host": host,
        "port": int(os.environ.get("DB_PORT", "5432")),
    }


def _connector_engine(cfg: dict):
    """Async SQLAlchemy engine that dials Cloud SQL via the Python Connector (no unix socket).

    Google's documented async pattern: `create_async_engine("postgresql+asyncpg://",
    async_creator=getconn)`, where `getconn` returns a raw asyncpg connection from the
    Connector. The Connector is created lazily on first use so it binds to the running event
    loop (the engine is built synchronously at app construction, before the loop is running).
    """
    from google.cloud.sql.connector import IPTypes, create_async_connector
    from sqlalchemy.ext.asyncio import create_async_engine

    ip_type = IPTypes.PRIVATE if cfg["private_ip"] else IPTypes.PUBLIC
    state: dict = {"connector": None}

    async def getconn():
        if state["connector"] is None:
            state["connector"] = await create_async_connector()
        return await state["connector"].connect_async(
            cfg["instance"],
            "asyncpg",
            user=cfg["user"],
            password=cfg["password"],
            db=cfg["database"],
            ip_type=ip_type,
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
    """The shared async SQLAlchemy engine, or None when no DB is configured.

    Cached: built once per process. A configured-but-undrivable DB (missing SQLAlchemy /
    connector) raises ImportError rather than silently returning None — a misconfigured DB
    must not degrade to a store that loses data.
    """
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
