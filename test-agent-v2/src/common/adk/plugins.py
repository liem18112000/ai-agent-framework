"""Cross-cutting ADK plugins — the head-of-request work v1 copy-pasted into every executor, now
registered once on the Runner (mapping §6).

- LearnDrainPlugin  (before_run): flush pending self-learning captures off-path + drain the pgvector
  index projection. No-op unless CAPTURE_LESSONS / MEMORY_BACKEND enable them. Invariants I2/I3.
- LessonRecallPlugin (before_model): inject grounded, scope='shared' lessons into the model request
  (B4/B5). Best-effort + flag-gated; conservative here, fully wired in A1 once the pack ctx is on state.
"""

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
            await asyncio.to_thread(learn.drain, bank, now=now())  # off-path (I3)
        try:
            from common.memory.pg.project import maybe_drain_index

            await maybe_drain_index(bank)  # no-op under MEMORY_BACKEND=gcs
        except Exception:
            log.debug("index drain skipped", exc_info=True)
        return


class LessonRecallPlugin(BasePlugin):
    def __init__(self) -> None:
        super().__init__(name="lesson_recall")

    async def before_model_callback(self, *, callback_context, llm_request):
        # Conservative for A.0: only act when recall is explicitly enabled; wire the grounded,
        # scope='shared' injection to the session's pack ctx in A1. Never break a model call.
        try:
            prefix = _agent_prefix(getattr(callback_context, "_invocation_context", callback_context))
            if not learn.recall_enabled(prefix):
                return
            # A1: recall_lessons(bank, seed_refs=<pack seed refs from state>) → append_instructions(...)
        except Exception:
            log.debug("lesson recall skipped", exc_info=True)
        return
