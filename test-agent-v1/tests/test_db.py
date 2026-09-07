"""M0: shared DB engine factory — env resolution + cached engine (no live DB)."""

from __future__ import annotations

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
    monkeypatch.setenv("DB_INSTANCE_CONNECTION_NAME", "proj:reg:inst")  # no user/pw/name
    assert db._db_config() is None
    assert db.get_engine() is None


def test_engine_cached_and_reset(monkeypatch):
    assert db.get_engine() is None                       # no DB → None, cached
    monkeypatch.setenv("TASK_DB_URL", "postgresql+asyncpg://u:p@localhost/db")
    assert db.get_engine() is None                       # still cached-None until reset
    db.reset_engine_cache()
    eng = db.get_engine()
    assert eng is not None                                # engine built (no connection opened)
    assert db.get_engine() is eng                         # same cached instance
