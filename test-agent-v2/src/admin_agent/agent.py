"""Admin root agent (ADK) — a deterministic, registry-dispatched text router (mirrors KgaRouter), NO LLM.

Commands self-register via `@command`, so adding an admin verb is a single localized addition — a new
decorated handler — and the dispatch loop + usage string never change (Open/Closed). Each handler has
one job: parse its `rest` and delegate to `common.admin` (Single-Responsibility). Blocking GCS + async
SQLAlchemy run off the event loop (`_bank_call` for the sync handlers; the DB handlers await directly).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from common import admin
from common.adk.router import RouterAgent
from common.memory.factory import build_bank
from common.monitoring import get_logger

log = get_logger("admin.router")

_Handler = Callable[["AdminRouter", str], Awaitable[str]]
_COMMANDS: dict[str, tuple[_Handler, str]] = {}  # name -> (handler, usage); filled by @command at import


def command(name: str, usage: str) -> Callable[[_Handler], _Handler]:
    """Register an AdminRouter handler under `name` (Open/Closed: a new verb is a new decorated method)."""
    def deco(fn: _Handler) -> _Handler:
        _COMMANDS[name] = (fn, usage)
        return fn
    return deco


def _usage() -> str:
    return "Admin verbs: " + " | ".join(u for _, u in _COMMANDS.values()) + "."


class AdminRouter(RouterAgent):
    async def _run_async_impl(self, ctx):
        yield self.reply(await self._dispatch(self.read(ctx).strip()))

    async def _dispatch(self, text: str) -> str:
        """Look up the command in the registry and run its handler — the loop never grows per verb."""
        cmd, _, rest = text.partition(" ")
        cmd, rest = cmd.lower(), rest.strip()
        entry = _COMMANDS.get(cmd)
        if entry is None:
            return _usage()
        try:
            return await entry[0](self, rest)
        except Exception as exc:  # noqa: BLE001 — an admin read/reset failure returns a message, never crashes
            log.warning("admin: %s failed (%s)", cmd, exc)
            return f"admin {cmd}: failed ({exc})"

    # --- shared resource access (one place builds the bank / engine off the loop) --------------------
    async def _bank_call(self, fn: Callable[[object], str]) -> str:
        """Run a sync `common.admin` call — bank build + its blocking GCS I/O — fully off the loop."""
        return await asyncio.to_thread(lambda: fn(build_bank()))

    async def _bank(self):
        """A MemoryBank built off the loop, for the async admin handlers (they thread their own I/O)."""
        return await asyncio.to_thread(build_bank)

    def _engine(self):
        from common.db import get_engine

        return get_engine()

    # --- commands — each self-contained; register via @command, so the dispatcher stays closed --------
    @command("list-runs", "list-runs [limit]")
    async def _list_runs(self, rest: str) -> str:
        limit = int(rest) if rest.isdigit() else 50
        return await self._bank_call(lambda b: admin.list_runs(b, limit))

    @command("get-run", "get-run <ctx>")
    async def _get_run(self, rest: str) -> str:
        if not rest:
            return "Provide a context id: get-run <ctx>."
        return await self._bank_call(lambda b: admin.get_run(b, rest))

    @command("compare-runs", "compare-runs <ctx-a> <ctx-b>")
    async def _compare_runs(self, rest: str) -> str:
        parts = rest.split()
        if len(parts) != 2:
            return "Provide two run ids: compare-runs <ctx-a> <ctx-b>."
        return await self._bank_call(lambda b: admin.compare_runs(b, parts[0], parts[1]))

    @command("backup-memory", "backup-memory <summary>")
    async def _backup_memory(self, rest: str) -> str:
        if not rest:
            return "Provide a summary: backup-memory <summary>."
        return await self._bank_call(lambda b: admin.backup_memory(b, rest))

    @command("list-backups", "list-backups")
    async def _list_backups(self, rest: str) -> str:
        return await self._bank_call(admin.list_backups)

    @command("view-memory", "view-memory [all|working|episodic|semantic|procedural] [ctx]")
    async def _view_memory(self, rest: str) -> str:
        parts = rest.split()
        tier = parts[0] if parts else "all"
        context_id = parts[1] if len(parts) > 1 else None
        return await admin.view_memory(await self._bank(), self._engine(), tier, context_id)

    @command("wipe-all", "wipe-all <confirm>")
    async def _wipe_all(self, rest: str) -> str:
        return await admin.wipe_all(await self._bank(), self._engine(), rest.strip())


def build_root_agent() -> AdminRouter:
    return AdminRouter(name="admin_agent")


root_agent = build_root_agent()
