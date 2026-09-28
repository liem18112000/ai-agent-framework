"""Offline/local run ledger — the in-memory fallback used when no DB is configured (get_engine() is
None), so the agent still runs end-to-end in docker-compose-local and tests. Same interface as ExecStore."""

from __future__ import annotations

from test_executor.store.ids import _now, env_id, new_id


class InMemoryExecStore:
    """Offline/local fallback (no DB configured) — same interface, process-lifetime dict state."""

    def __init__(self) -> None:
        self._envs: dict[str, dict] = {}
        self._runs: dict[str, dict] = {}

    async def upsert_env(self, context_id, name, *, base_url="", kind=None, revision=None,
                         creds_ref=None, health=None) -> str:
        eid = env_id(context_id, name)
        row = self._envs.get(eid) or {"id": eid, "context_id": context_id, "name": name,
                                      "first_seen": _now()}
        row.update({"base_url": base_url, "kind": kind, "revision": revision, "creds_ref": creds_ref,
                    "health": health or {}, "last_seen": _now()})
        self._envs[eid] = row
        return eid

    async def start_run(self, context_id, environment_id) -> str:
        active = next((r for r in self._runs.values()
                       if r["context_id"] == context_id and r["status"] == "in_progress"), None)
        if active is not None:  # one active run per context (parity with ExecStore)
            return active["id"]
        rid = new_id()
        self._runs[rid] = {"id": rid, "context_id": context_id, "environment_id": environment_id,
                           "status": "in_progress", "summary": {}, "signals": {}, "triage": [],
                           "trace_uri": None, "started_at": _now(), "finished_at": None}
        return rid

    async def save_progress(self, run_id, *, summary, signals) -> None:
        r = self._runs.get(run_id)
        if r is not None:
            r.update({"status": "in_progress", "summary": summary, "signals": signals})

    async def finish_run(self, run_id, *, status, summary, signals, triage=None, trace_uri=None) -> None:
        r = self._runs.get(run_id)
        if r is None:
            return
        r.update({"status": status, "summary": summary, "signals": signals, "triage": triage or [],
                  "trace_uri": trace_uri, "finished_at": _now()})

    async def get_run(self, *, run_id=None, context_id=None) -> dict | None:
        if run_id:
            return self._runs.get(run_id)
        runs = [r for r in self._runs.values() if r["context_id"] == context_id]
        return max(runs, key=lambda r: r["started_at"]) if runs else None

    async def list_environments(self, context_id) -> list[dict]:
        envs = [e for e in self._envs.values() if e["context_id"] == context_id]
        return sorted(envs, key=lambda e: e["last_seen"], reverse=True)
