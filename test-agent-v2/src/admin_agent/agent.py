"""Admin root agent (ADK) — a deterministic, registry-dispatched text router (mirrors KgaRouter), NO LLM.

`_commands()` is one literal `{verb: (handler, usage)}` table — adding an admin verb is a new method
plus one line here; the dispatch loop + usage string derive from the table. Each handler has one job:
parse its `rest` and delegate to `common.admin` (Single-Responsibility). Blocking GCS + async
SQLAlchemy run off the event loop (`_bank_call` for the sync handlers; the DB handlers await directly).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from common import admin
from common.adk.router import RouterAgent
from common.admin import prompts as admin_prompts
from common.memory.factory import build_bank
from common.monitoring import get_logger

log = get_logger("admin.router")

_Handler = Callable[[str], Awaitable[str]]  # a bound handler: (rest) -> reply


class AdminRouter(RouterAgent):
    async def _run_async_impl(self, ctx):
        yield self.reply(await self._dispatch(self.read(ctx).strip()))

    def _commands(self) -> dict[str, tuple[_Handler, str]]:
        """The verb table: name -> (bound handler, usage). One literal dict, no import-time registry."""
        return {
            "list-runs": (self._list_runs, "list-runs [limit]"),
            "get-run": (self._get_run, "get-run <ctx>"),
            "compare-runs": (self._compare_runs, "compare-runs <ctx-a> <ctx-b>"),
            "prompt-list": (self._prompt_list, "prompt-list"),
            "prompt-seed": (self._prompt_seed, "prompt-seed [force]"),
            "prompt-get": (self._prompt_get, "prompt-get <key>"),
            "prompt-publish": (self._prompt_publish, "prompt-publish <json>"),
            "prompt-rollback": (self._prompt_rollback, "prompt-rollback <key> <version>"),
            "prompt-history": (self._prompt_history, "prompt-history <key>"),
            "backup-memory": (self._backup_memory, "backup-memory <summary>"),
            "list-backups": (self._list_backups, "list-backups"),
            "view-memory": (self._view_memory, "view-memory [all|working|episodic|semantic|procedural] [ctx]"),
            "memory-graph": (self._memory_graph, "memory-graph [title]"),
            "wipe-all": (self._wipe_all, "wipe-all <confirm>"),
            "forget-memory": (self._forget_memory, "forget-memory [confirm]"),
        }

    async def _dispatch(self, text: str) -> str:
        """Look up the command in the verb table and run its handler."""
        cmd, _, rest = text.partition(" ")
        cmd, rest = cmd.lower(), rest.strip()
        table = self._commands()
        entry = table.get(cmd)
        if entry is None:
            return "Admin verbs: " + " | ".join(u for _, u in table.values()) + "."
        try:
            return await entry[0](rest)
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

    # --- commands — each self-contained; wired into the verb table in `_commands` --------------------
    async def _list_runs(self, rest: str) -> str:
        limit = int(rest) if rest.isdigit() else 50
        return await self._bank_call(lambda b: admin.list_runs(b, limit))

    async def _get_run(self, rest: str) -> str:
        if not rest:
            return "Provide a context id: get-run <ctx>."
        return await self._bank_call(lambda b: admin.get_run(b, rest))

    async def _compare_runs(self, rest: str) -> str:
        parts = rest.split()
        if len(parts) != 2:
            return "Provide two run ids: compare-runs <ctx-a> <ctx-b>."
        return await self._bank_call(lambda b: admin.compare_runs(b, parts[0], parts[1]))

    # --- P3: the prompt store (read / publish / roll back / audit) ---------------------------
    async def _prompt_list(self, rest: str) -> str:
        return await admin_prompts.list_prompts()

    async def _prompt_seed(self, rest: str) -> str:
        return await admin_prompts.seed_prompts(force=rest.strip().lower() in ("force", "1", "true"))

    async def _prompt_get(self, rest: str) -> str:
        if not rest:
            return "Provide a key: prompt-get <key>."
        return await admin_prompts.get_prompt(rest.strip())

    async def _prompt_publish(self, rest: str) -> str:
        if not rest:
            return 'Provide a JSON payload: {"key": ..., "body": ...}.'
        return await admin_prompts.publish_prompt(rest)

    async def _prompt_rollback(self, rest: str) -> str:
        parts = rest.split()
        if len(parts) != 2 or not parts[1].isdigit():
            return "Usage: prompt-rollback <key> <version>."
        return await admin_prompts.rollback_prompt(parts[0], int(parts[1]))

    async def _prompt_history(self, rest: str) -> str:
        if not rest:
            return "Provide a key: prompt-history <key>."
        return await admin_prompts.prompt_history(rest.strip())

    async def _backup_memory(self, rest: str) -> str:
        if not rest:
            return "Provide a summary: backup-memory <summary>."
        return await self._bank_call(lambda b: admin.backup_memory(b, rest))

    async def _list_backups(self, rest: str) -> str:
        return await self._bank_call(admin.list_backups)

    async def _view_memory(self, rest: str) -> str:
        parts = rest.split()
        tier = parts[0] if parts else "all"
        context_id = parts[1] if len(parts) > 1 else None
        return await admin.view_memory(await self._bank(), self._engine(), tier, context_id)

    async def _memory_graph(self, rest: str) -> str:
        """Render memory_node + memory_edge as a self-contained force-directed HTML page (graphify-style).
        Returns the HTML itself — the client writes it to a file and publishes it via the Artifact tool."""
        title = rest.strip() or "Memory graph"
        return await admin.memory_graph_html(await self._bank(), self._engine(), title=title)

    async def _wipe_all(self, rest: str) -> str:
        return await admin.wipe_all(await self._bank(), self._engine(), rest.strip())

    async def _forget_memory(self, rest: str) -> str:
        """Forget everything LEARNED (bank + pgvector) — nothing else. Two-phase: called bare it
        previews what would go and returns the token; only the second call with that token deletes."""
        return await admin.forget_memory(await self._bank(), self._engine(), rest.strip())


def build_root_agent() -> AdminRouter:
    return AdminRouter(name="admin_agent")


root_agent = build_root_agent()
