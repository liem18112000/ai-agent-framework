"""M0: shared DB engine factory — env resolution + cached engine (no live DB)."""

from __future__ import annotations

import asyncio

import pytest

from common import db

_KEYS = ["TASK_DB_URL", "DB_INSTANCE_CONNECTION_NAME", "DB_HOST", "DB_PORT",
         "DB_USER", "DB_PASSWORD", "DB_NAME", "DB_USE_PRIVATE_IP"]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for k in _KEYS:
        monkeypatch.delenv(k, raising=False)
    db.reset_engine_cache()
    yield
    db.reset_engine_cache()


def test_no_env_is_no_db():
    assert db._db_config() is None
    assert db.get_engine() is None


def test_url_wins(monkeypatch):
    monkeypatch.setenv("TASK_DB_URL", "postgresql+asyncpg://u:p@localhost/db")
    assert db._db_config() == {"kind": "url", "url": "postgresql+asyncpg://u:p@localhost/db"}


def test_connector_config(monkeypatch):
    monkeypatch.setenv("DB_INSTANCE_CONNECTION_NAME", "proj:reg:inst")
    monkeypatch.setenv("DB_USER", "u")
    monkeypatch.setenv("DB_PASSWORD", "pw")
    monkeypatch.setenv("DB_NAME", "n")
    cfg = db._db_config()
    assert cfg["kind"] == "connector"
    assert cfg["instance"] == "proj:reg:inst"
    assert cfg["private_ip"] is False


def test_tcp_config(monkeypatch):
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_USER", "u")
    monkeypatch.setenv("DB_PASSWORD", "pw")
    monkeypatch.setenv("DB_NAME", "n")
    cfg = db._db_config()
    assert cfg["kind"] == "tcp"
    assert cfg["host"] == "localhost"
    assert cfg["port"] == 5432


def test_missing_creds_is_no_db(monkeypatch):
    monkeypatch.setenv("DB_INSTANCE_CONNECTION_NAME", "proj:reg:inst")
    assert db._db_config() is None
    assert db.get_engine() is None


def test_engine_cached_and_reset(monkeypatch):
    assert db.get_engine() is None
    monkeypatch.setenv("TASK_DB_URL", "postgresql+asyncpg://u:p@localhost/db")
    assert db.get_engine() is None
    db.reset_engine_cache()
    eng = db.get_engine()
    assert eng is not None
    assert db.get_engine() is eng


# --- SchemaOnce: the lazy DDL apply both SQL stores inherit -------------------------------------
# It had no offline coverage at all (only the skipped pg-integration file called `_ensure`), and it
# used to exist as two byte-identical copies — so the race fix it carries was untested twice over.


class _FakeConn:
    def __init__(self, seen):
        self._seen = seen

    async def execute(self, stmt, *_a):
        self._seen.append(str(stmt))


class _FakeEngine:
    """Records every statement, and yields the event loop inside begin() so a concurrent first
    caller genuinely interleaves — without that await the race can't be reproduced."""

    def __init__(self):
        self.seen: list[str] = []
        self.begins = 0

    def begin(self):
        engine = self

        class _Ctx:
            async def __aenter__(self):
                engine.begins += 1
                await asyncio.sleep(0)
                return _FakeConn(engine.seen)

            async def __aexit__(self, *_exc):
                return False

        return _Ctx()


class _Store(db.SchemaOnce):
    SCHEMA_SQL = "CREATE TABLE a (id text);\nCREATE INDEX i ON a (id);\n"


async def test_schema_once_applies_each_statement_exactly_once():
    eng = _FakeEngine()
    store = _Store(eng)
    for _ in range(3):
        await store._ensure()
    assert eng.seen == ["CREATE TABLE a (id text)", "CREATE INDEX i ON a (id)"]
    assert eng.begins == 1


async def test_schema_once_serialises_concurrent_first_callers():
    """Two first callers racing CREATE EXTENSION/INDEX raise `tuple concurrently updated` and the
    store then degrades silently (MEM-02) — the lock is the whole point of this class."""
    eng = _FakeEngine()
    store = _Store(eng)
    await asyncio.gather(*(store._ensure() for _ in range(5)))
    assert eng.begins == 1


async def test_each_subclass_applies_its_own_schema():
    """The refactor's real risk: both stores inheriting one SCHEMA_SQL instead of their own."""
    from common.memory.pg.store import PgMemoryStore
    from test_executor.store.sql import ExecStore

    assert "memory_node" in PgMemoryStore.SCHEMA_SQL
    assert "exec_run" in ExecStore.SCHEMA_SQL
    assert PgMemoryStore.SCHEMA_SQL != ExecStore.SCHEMA_SQL

    eng = _FakeEngine()
    await ExecStore(eng)._ensure()
    assert any("exec_environment" in s for s in eng.seen)
    assert not any("memory_node" in s for s in eng.seen)
