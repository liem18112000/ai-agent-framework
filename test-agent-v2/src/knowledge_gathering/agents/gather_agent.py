"""GatherAgent — the KGA crawl engine as a custom ADK BaseAgent.

Re-triggers v1's gather pipeline verbatim (parse → seed probe → fan-out → bounded BFS crawl →
summarize), reusing the exact functions from `executor/gather.py`. The crawl/fan-out are already
async I/O (LLM + codegraph work is offloaded inside them), so we await them directly. Determinism +
B0–B6 + the heuristic distiller (distiller=None) are unchanged (invariants I1/I2). run_id = the ADK
session id (== the pipeline context id the bridge holds constant), so the pack is run-scoped (B0).
"""

from __future__ import annotations

from google.adk.agents import BaseAgent

from common.adk.events import incoming_text, text_event
from common.memory.factory import build_bank
from common.models import Scope
from knowledge_gathering.atlassian_client import build_client
from knowledge_gathering.explore.expand import expansion_round
from knowledge_gathering.gather import (
    _capture_gather,
    _explore_loop_enabled,
    _follow_web_enabled,
    _seed_probe,
    parse_input,
    summarize_gather,
)
from knowledge_gathering.loop import crawl
from knowledge_gathering.monitoring import get_logger

log = get_logger("adk.gather")


class GatherAgent(BaseAgent):
    async def _run_async_impl(self, ctx):
        text = incoming_text(ctx).strip()
        seed, depth, repo, _exclude = parse_input(text)  # _exclude: used by the explore loop (A1 follow-up)
        if not seed:
            yield text_event(self.name, "Provide a seed, e.g. 'gather LUZ-158390 depth 2'.")
            return
        try:
            client = build_client()
            bank = build_bank()
        except Exception as exc:  # noqa: BLE001 — missing config/creds → graceful reply
            yield text_event(self.name, f"Config error: {exc}")
            return

        run_id = ctx.session.id
        extra_seeds = [repo] if repo else []
        max_seconds = 600.0 if repo else 180.0
        probe = await _seed_probe(client, seed)
        scope = Scope(follow_web=True) if _follow_web_enabled() else None
        if _explore_loop_enabled():
            log.warning("KGA_EXPLORE_LOOP is on but the explore-loop path is not yet ported to ADK "
                        "(A1 follow-up); running the single-pass fan-out.")

        new_seeds, md_blocks = await expansion_round(
            bank, client, seed=seed, terms=probe.terms, thin=probe.thin, project=probe.project,
            title=probe.title, description=probe.description, labels=probe.labels,
            parent=probe.parent, exclude=set(extra_seeds))
        extra_seeds += [s for s in new_seeds if s not in extra_seeds]

        result = await crawl(client, bank, seed, depth=depth, scope=scope, distiller=None,
                             run_id=run_id, extra_seeds=extra_seeds or None, max_seconds=max_seconds)
        summary = summarize_gather(result)
        for md in md_blocks:
            summary += "\n\n" + md
        _capture_gather(bank, context_id=run_id or seed, seed=seed, result=result)  # L3, flag-gated
        yield text_event(self.name, summary)
