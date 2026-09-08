"""GatherAgent — the KGA crawl engine as a custom ADK BaseAgent.

D15: GatherAgent stays the deterministic custom `BaseAgent` orchestrator (D1). When the opt-in flags
are set it now DRIVES two leaf `LlmAgent` planners (hypothesize / leads) through its own `ctx`,
reads their validated output from `session.state`, and feeds `terms=`/`leads=` into the unchanged
deterministic `expansion_round` + `crawl`. With both flags OFF (default) no planner runs and the path
makes ZERO LLM calls, byte-for-byte as before (I1).
"""

from __future__ import annotations

import os

from google.adk.agents import BaseAgent

from common.adk.events import incoming_text, text_event
from common.atlassian import AtlassianClient
from common.memory.factory import build_bank
from common.models import Scope
from knowledge_gathering.explore.ask_llm import OUTPUT_KEY as LEADS_KEY
from knowledge_gathering.explore.ask_llm import leads_enabled
from knowledge_gathering.explore.expand import expansion_round
from knowledge_gathering.explore.hypothesize import OUTPUT_KEY as HYP_KEY
from knowledge_gathering.explore.hypothesize import hypothesize_enabled
from knowledge_gathering.explore.schemas import PLAN_INPUT_KEY, Hypothesis, Leads
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


def build_client() -> AtlassianClient:
    bb_user = os.environ.get("ATLASSIAN_BITBUCKET_USERNAME")
    bb_pass = os.environ.get("ATLASSIAN_BITBUCKET_APP_PASSWORD")
    return AtlassianClient(
        os.environ["ATLASSIAN_BASE_URL"],
        os.environ["ATLASSIAN_EMAIL"],
        os.environ["ATLASSIAN_API_TOKEN"],
        bitbucket_auth=(bb_user, bb_pass) if bb_user and bb_pass else None,
    )


class GatherAgent(BaseAgent):
    # The two opt-in explore planners (D15). Optional so tests can inject fake-model agents (or None
    # to force the deterministic path); `build_root_agent` wires the production ones as sub_agents.
    hypothesize_agent: BaseAgent | None = None
    leads_agent: BaseAgent | None = None

    async def _run_planner(self, ctx, agent, output_key: str) -> dict | None:
        """Run a leaf planner `LlmAgent` under `ctx`; return its validated `output_key` dict.

        Reads the value straight off the planner event's `state_delta` (we consume the planner's
        events internally rather than surfacing them, so no Runner applies the delta for us) and also
        writes it into `ctx.session.state` for the plan's read-from-state contract. A malformed model
        reply makes ADK raise `ValidationError` inside the planner; we catch it and degrade (→ None),
        preserving the old best-effort `""`/`[]` contract.
        """
        result: dict | None = None
        try:
            async for ev in agent.run_async(ctx):
                actions = getattr(ev, "actions", None)
                delta = getattr(actions, "state_delta", None) if actions else None
                if delta and output_key in delta:
                    result = delta[output_key]
                    ctx.session.state[output_key] = result
        except Exception as exc:  # noqa: BLE001 — planning is best-effort; must never break gather
            log.warning("KGA planner %r degraded (%s)", output_key, exc)
            return None
        return result

    async def _plan(self, ctx, probe) -> tuple[str, list[str] | None, list[str]]:
        """Run the opt-in planners behind their flags; return (focus_terms, leads, planner_md)."""
        terms = probe.terms
        leads: list[str] | None = None
        planner_md: list[str] = []
        if not probe.title or not (hypothesize_enabled() or leads_enabled()):
            return terms, leads, planner_md

        ctx.session.state[PLAN_INPUT_KEY] = {
            "title": probe.title, "description": probe.description, "labels": probe.labels or [],
        }
        if hypothesize_enabled() and self.hypothesize_agent is not None:
            raw = await self._run_planner(ctx, self.hypothesize_agent, HYP_KEY)
            hyp = Hypothesis(**raw).as_terms() if raw else ""
            if hyp:
                log.info("A2A gather: hypothesize enriched terms: %r", hyp)
                terms = hyp
                planner_md.append(f"Hypothesized focus: {hyp}")
        if leads_enabled() and self.leads_agent is not None:
            raw = await self._run_planner(ctx, self.leads_agent, LEADS_KEY)
            leads = Leads(**raw).as_leads() if raw else None
        return terms, leads, planner_md

    async def _run_async_impl(self, ctx):
        text = incoming_text(ctx).strip()
        seed, depth, repo, _exclude = parse_input(text)
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

        terms, leads, planner_md = await self._plan(ctx, probe)

        new_seeds, md_blocks = await expansion_round(
            bank, client, seed=seed, terms=terms, thin=probe.thin, project=probe.project,
            title=probe.title, description=probe.description, labels=probe.labels,
            parent=probe.parent, exclude=set(extra_seeds), leads=leads,
            allow_hypothesize=False, allow_leads=False)
        extra_seeds += [s for s in new_seeds if s not in extra_seeds]

        result = await crawl(client, bank, seed, depth=depth, scope=scope, distiller=None,
                             run_id=run_id, extra_seeds=extra_seeds or None, max_seconds=max_seconds)
        summary = summarize_gather(result)
        for md in planner_md + md_blocks:
            summary += "\n\n" + md
        _capture_gather(bank, context_id=run_id or seed, seed=seed, result=result)
        yield text_event(self.name, summary)
