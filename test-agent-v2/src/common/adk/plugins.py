"""Cross-cutting ADK plugins — the head-of-request work v1 copy-pasted into every executor, now"""

from __future__ import annotations

import asyncio

from google.adk.plugins import BasePlugin

from common import learn
from common.adk.events import now
from common.memory.factory import build_bank
from common.monitoring import get_logger

log = get_logger("adk.plugins")


def _agent_prefix(ictx) -> str:
    """"KGA"/"TPD" from the app/agent name, for the per-agent capture/recall flags."""
    name = (getattr(ictx, "app_name", "") or getattr(getattr(ictx, "agent", None), "name", "") or "").lower()
    return "TPD" if ("test-plan" in name or "test_plan" in name or "tpd" in name) else "KGA"


class LearnDrainPlugin(BasePlugin):
    def __init__(self) -> None:
        super().__init__(name="learn_drain")

    async def before_run_callback(self, *, invocation_context):
        try:
            bank = build_bank()
        except Exception:  # noqa: BLE001 — bank optional; never block the run on a config gap
            return
        prefix = _agent_prefix(invocation_context)
        if learn.capture_enabled(prefix):
            await asyncio.to_thread(learn.drain, bank, now=now())
        try:
            from common.memory.pg.project import maybe_drain_index

            await maybe_drain_index(bank)
        except Exception:
            log.debug("index drain skipped", exc_info=True)
