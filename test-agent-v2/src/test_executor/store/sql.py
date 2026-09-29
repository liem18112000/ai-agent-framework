"""Postgres-backed run ledger — two tables (`exec_environment`, `exec_run`) on the SHARED Cloud SQL
engine (common.db.get_engine). Design ref: RESEARCH-test-executor-agent.md §4.

We do NOT invent a datastore: this reuses the one async engine that already backs the A2A task store +
ADK sessions + pgvector, adding exactly two tables via the repo's raw `text()` + `CREATE TABLE IF NOT
EXISTS` idiom (mirrors common/memory/pg/store.py).
"""

from __future__ import annotations

import json

from common.db import SchemaOnce
from test_executor.store.ids import _j, env_id, new_id

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS exec_environment (
  id           text PRIMARY KEY,
  context_id   text NOT NULL,
  name         text NOT NULL,
  base_url     text NOT NULL DEFAULT '',
  kind         text,
  revision     text,
  creds_ref    text,
  health       jsonb NOT NULL DEFAULT '{}',
  first_seen   timestamptz NOT NULL DEFAULT now(),
  last_seen    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS exec_environment_ctx ON exec_environment (context_id);

CREATE TABLE IF NOT EXISTS exec_run (
  id             text PRIMARY KEY,
  context_id     text NOT NULL,
  environment_id text,
  status         text NOT NULL DEFAULT 'in_progress',
  summary        jsonb NOT NULL DEFAULT '{}',
  signals        jsonb NOT NULL DEFAULT '{}',
  triage         jsonb NOT NULL DEFAULT '[]',
  trace_uri      text,
  started_at     timestamptz NOT NULL DEFAULT now(),
  finished_at    timestamptz
);
CREATE INDEX IF NOT EXISTS exec_run_ctx ON exec_run (context_id);
"""


class ExecStore(SchemaOnce):
    """Postgres-backed run ledger on the shared async engine. Schema applied once per process."""

    SCHEMA_SQL = _SCHEMA_SQL

    async def upsert_env(self, context_id: str, name: str, *, base_url: str = "", kind: str | None = None,
                         revision: str | None = None, creds_ref: str | None = None,
                         health: dict | None = None) -> str:
        """Register/refresh one tested environment (new env → new row on first sight). Returns its id."""
        from sqlalchemy import text
        await self._ensure()
        eid = env_id(context_id, name)
        params = {"id": eid, "context_id": context_id, "name": name, "base_url": base_url,
                  "kind": kind, "revision": revision, "creds_ref": creds_ref,
                  "health": json.dumps(health or {})}
        sql = text(
            "INSERT INTO exec_environment (id,context_id,name,base_url,kind,revision,creds_ref,health) "
            "VALUES (:id,:context_id,:name,:base_url,:kind,:revision,:creds_ref,CAST(:health AS jsonb)) "
            "ON CONFLICT (id) DO UPDATE SET base_url=EXCLUDED.base_url, kind=EXCLUDED.kind, "
            "revision=EXCLUDED.revision, creds_ref=EXCLUDED.creds_ref, health=EXCLUDED.health, "
            "last_seen=now()")
        async with self._engine.begin() as conn:
            await conn.execute(sql, params)
        return eid

    async def start_run(self, context_id: str, environment_id: str | None) -> str:
        """Open a fresh run — but only if the context has no `in_progress` run (one active run per
        context). Two concurrent fresh starts would otherwise leave a second, orphaned in_progress row;
        the conditional insert converges them onto one. (The per-chunk cursor still assumes the
        documented sequential-poll contract — one poll in flight at a time — so a run advances once.)"""
        from sqlalchemy import text
        await self._ensure()
        rid = new_id()
        sql = text("INSERT INTO exec_run (id,context_id,environment_id,status) "
                   "SELECT :id,:context_id,:environment_id,'in_progress' "
                   "WHERE NOT EXISTS (SELECT 1 FROM exec_run WHERE context_id=:context_id "
                   "AND status='in_progress')")
        async with self._engine.begin() as conn:
            inserted = (await conn.execute(sql, {"id": rid, "context_id": context_id,
                                                 "environment_id": environment_id})).rowcount
        if not inserted:  # a run is already active for this context → reuse it, never double-start
            existing = await self.get_run(context_id=context_id)
            if existing and existing.get("status") == "in_progress":
                return existing["id"]
        return rid

    async def save_progress(self, run_id: str, *, summary: dict, signals: dict) -> None:
        """Checkpoint a still-running chunked run (status stays in_progress; no finished_at)."""
        from sqlalchemy import text
        await self._ensure()
        sql = text("UPDATE exec_run SET status='in_progress', summary=CAST(:summary AS jsonb), "
                   "signals=CAST(:signals AS jsonb) WHERE id=:id")
        async with self._engine.begin() as conn:
            await conn.execute(sql, {"id": run_id, "summary": json.dumps(summary),
                                     "signals": json.dumps(signals)})

    async def finish_run(self, run_id: str, *, status: str, summary: dict, signals: dict,
                         triage: list | None = None, trace_uri: str | None = None) -> None:
        from sqlalchemy import text
        await self._ensure()
        sql = text("UPDATE exec_run SET status=:status, summary=CAST(:summary AS jsonb), "
                   "signals=CAST(:signals AS jsonb), triage=CAST(:triage AS jsonb), "
                   "trace_uri=:trace_uri, finished_at=now() WHERE id=:id")
        async with self._engine.begin() as conn:
            await conn.execute(sql, {"id": run_id, "status": status, "summary": json.dumps(summary),
                                     "signals": json.dumps(signals), "triage": json.dumps(triage or []),
                                     "trace_uri": trace_uri})

    async def get_run(self, *, run_id: str | None = None, context_id: str | None = None) -> dict | None:
        from sqlalchemy import text
        await self._ensure()
        if run_id:
            sql = text("SELECT * FROM exec_run WHERE id=:k")
            key = {"k": run_id}
        else:
            sql = text("SELECT * FROM exec_run WHERE context_id=:k ORDER BY started_at DESC LIMIT 1")
            key = {"k": context_id}
        async with self._engine.begin() as conn:
            row = (await conn.execute(sql, key)).mappings().first()
        return _row_run(row) if row else None

    async def list_environments(self, context_id: str) -> list[dict]:
        from sqlalchemy import text
        await self._ensure()
        sql = text("SELECT * FROM exec_environment WHERE context_id=:c ORDER BY last_seen DESC")
        async with self._engine.begin() as conn:
            rows = (await conn.execute(sql, {"c": context_id})).mappings().all()
        return [_row_env(r) for r in rows]


def _row_run(r) -> dict:
    d = dict(r)
    for k in ("summary", "signals", "triage"):
        d[k] = _j(d.get(k))
    return d


def _row_env(r) -> dict:
    d = dict(r)
    d["health"] = _j(d.get("health"))
    return d
