"""Admin root agent (ADK) — a deterministic text-dispatch router (mirrors KgaRouter), NO LLM.

All six admin verbs are deterministic aggregation / SQL / blob work, so there is no LLM hop and no
sub-agent. Blocking GCS + async SQLAlchemy run off the event loop (`asyncio.to_thread` for the GCS-only
handlers; the DB handlers are async and awaited directly).
"""

from __future__ import annotations

import asyncio

from google.adk.agents import BaseAgent

from common import admin
from common.adk.events import incoming_text, text_event
from common.memory.factory import build_bank
from common.monitoring import get_logger

log = get_logger("admin.router")

_USAGE = ("Admin verbs: list-runs [limit] | get-run <ctx> | "
          "view-memory [all|working|episodic|semantic|procedural] [ctx] | "
          "backup-memory <summary> | list-backups | wipe-all <confirm>.")


class AdminRouter(BaseAgent):
    async def _run_async_impl(self, ctx):
        text = incoming_text(ctx).strip()
        yield text_event(self.name, await self._dispatch(text))

    async def _dispatch(self, text: str) -> str:
        cmd, _, rest = text.partition(" ")
        cmd, rest = cmd.lower(), rest.strip()
        try:
            if cmd == "list-runs":
                limit = int(rest) if rest.isdigit() else 50
                return await asyncio.to_thread(lambda: admin.list_runs(build_bank(), limit))
            if cmd == "get-run":
                if not rest:
                    return "Provide a context id: get-run <ctx>."
                return await asyncio.to_thread(lambda: admin.get_run(build_bank(), rest))
            if cmd == "backup-memory":
                if not rest:
                    return "Provide a summary: backup-memory <summary>."
                return await asyncio.to_thread(lambda: admin.backup_memory(build_bank(), rest))
            if cmd == "list-backups":
                return await asyncio.to_thread(lambda: admin.list_backups(build_bank()))
            if cmd == "view-memory":
                return await self._view(rest)
            if cmd == "wipe-all":
                return await self._wipe(rest)
        except Exception as exc:  # noqa: BLE001 — an admin read/reset failure returns a message, never crashes
            log.warning("admin: %s failed (%s)", cmd, exc)
            return f"admin {cmd}: failed ({exc})"
        return _USAGE

    async def _view(self, rest: str) -> str:
        from common.db import get_engine

        parts = rest.split()
        tier = parts[0] if parts else "all"
        context_id = parts[1] if len(parts) > 1 else None
        bank = await asyncio.to_thread(build_bank)
        return await admin.view_memory(bank, get_engine(), tier, context_id)

    async def _wipe(self, rest: str) -> str:
        from common.db import get_engine

        bank = await asyncio.to_thread(build_bank)
        return await admin.wipe_all(bank, get_engine(), rest.strip())


def build_root_agent() -> AdminRouter:
    return AdminRouter(name="admin_agent")


root_agent = build_root_agent()
