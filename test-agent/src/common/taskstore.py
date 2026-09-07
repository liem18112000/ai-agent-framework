"""A2A task-store factory shared by both agent servers.

`DefaultRequestHandler` persists A2A `Task` objects via a `TaskStore`. The default
`InMemoryTaskStore` loses every task when the Cloud Run instance restarts / scales to
zero / gets a new revision, and cannot be shared across instances. `build_task_store()`
returns a durable Postgres-backed `DatabaseTaskStore` (a2a-sdk) when the DB env is
present, and otherwise falls back to in-memory — so local dev and tests need no DB.

Configuration (set by terraform on Cloud Run; see deployments/cloudsql.tf):

  * TASK_DB_URL                  — full SQLAlchemy async URL; wins over everything else.
  * DB_INSTANCE_CONNECTION_NAME  — Cloud SQL "PROJECT:REGION:INSTANCE"; connect via the
    Cloud SQL Python Connector (IAM-authenticated + TLS, dialed over the container's
    egress). Requires DB_USER, DB_PASSWORD, DB_NAME. Optional DB_USE_PRIVATE_IP=1 to
    dial the instance's private IP instead of its public IP.
  * DB_HOST (+ DB_PORT)          — plain TCP host (local docker-compose / a proxy on
    localhost). Requires DB_USER, DB_PASSWORD, DB_NAME.
  * none of the above           — InMemoryTaskStore.

Why the Connector and NOT the managed /cloudsql unix socket: Cloud Run's automatic
Cloud SQL socket mount does not reach a *sidecar* container in a multi-container service
(only the ingress container), so the agent container — which is the sidecar here — sees
no socket and asyncpg raises FileNotFoundError. The Cloud SQL Python Connector sidesteps
the socket entirely: it opens an IAM-authenticated TLS connection straight to the instance
(needs roles/cloudsql.client + the Cloud SQL Admin API, both provisioned in cloudsql.tf).

The engine is created eagerly (cheap, synchronous — no connection is opened yet). The
Connector is created lazily on the first real connection, inside the running event loop.
`DatabaseTaskStore` creates the `tasks` table lazily on first use, so no startup await.
"""

from __future__ import annotations

import os

from a2a.server.tasks import InMemoryTaskStore, TaskStore

from common.monitoring import get_logger

log = get_logger("taskstore")


def _db_config() -> dict | None:
    """Resolve DB connection settings from env into a tagged config dict, or None.

    Returns one of:
      * {"kind": "url", "url": <str>}                             — TASK_DB_URL passthrough
      * {"kind": "connector", "instance", "user", ...}            — Cloud SQL Python Connector
      * {"kind": "tcp", "username", "password", "host", "port"}   — plain TCP
      * None                                                      — no DB configured (in-memory)
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
        log.warning("DB target set but %s missing — falling back to in-memory task store", ", ".join(missing))
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
    Connector. The Connector is created lazily on first use so it binds to the running
    event loop (build_task_store is called synchronously at app construction, before the
    loop is running).
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


def build_task_store() -> TaskStore:
    """Return a durable DatabaseTaskStore when a DB is configured, else InMemoryTaskStore."""
    cfg = _db_config()
    if cfg is None:
        log.info("task store: in-memory (no DB configured)")
        return InMemoryTaskStore()

    try:
        from a2a.server.tasks import DatabaseTaskStore
        from sqlalchemy import URL
        from sqlalchemy.ext.asyncio import create_async_engine
    except ImportError:
        # Missing driver shouldn't silently drop us to a store that loses tasks.
        log.error("DB configured but a2a-sdk[postgresql] is not installed — install it (SQLAlchemy + asyncpg)")
        raise

    if cfg["kind"] == "connector":
        try:
            engine = _connector_engine(cfg)
        except ImportError:
            log.error("Cloud SQL configured but cloud-sql-python-connector is not installed — install it")
            raise
    elif cfg["kind"] == "url":
        engine = create_async_engine(cfg["url"], pool_pre_ping=True)
    else:  # tcp
        kwargs = {k: cfg[k] for k in ("username", "password", "database", "host", "port")}
        engine = create_async_engine(URL.create("postgresql+asyncpg", **kwargs), pool_pre_ping=True)

    log.info("task store: Postgres via DatabaseTaskStore (%s)", engine.url.render_as_string(hide_password=True))
    return DatabaseTaskStore(engine, create_table=True)
