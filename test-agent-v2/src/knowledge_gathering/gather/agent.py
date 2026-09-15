"""GatherAgent — the KGA crawl engine as a custom ADK BaseAgent."""

from __future__ import annotations

import contextlib

from google.adk.agents import BaseAgent

from common.adk.events import incoming_text, text_event
from common.atlassian import AtlassianClient
from common.atlassian.factory import build_client
from common.cloud import cloud_configured, cloud_max_services
from common.memory import MemoryBank
from common.memory.factory import build_bank
from common.models import Scope
from knowledge_gathering.gather.crawl import crawl
from knowledge_gathering.gather.domain import (
    capture_gather,
    exclude_ids,
    parse_input,
    seed_probe,
    summarize_gather,
)
from knowledge_gathering.gather.explore.expand import expansion_round
from knowledge_gathering.gather.explore.planners.ask_llm import OUTPUT_KEY as LEADS_KEY
from knowledge_gathering.gather.explore.planners.ask_llm import build_leads_agent
from knowledge_gathering.gather.explore.planners.cloud_explore import OUTPUT_KEY as CLOUD_KEY
from knowledge_gathering.gather.explore.planners.cloud_explore import build_cloud_explore_agent
from knowledge_gathering.gather.explore.planners.hypothesize import OUTPUT_KEY as HYP_KEY
from knowledge_gathering.gather.explore.planners.hypothesize import build_hypothesize_agent
from knowledge_gathering.gather.explore.planners.schemas import (
    PLAN_INPUT_KEY,
    CloudExplorePlan,
    Hypothesis,
    Leads,
    PlanInput,
)
from knowledge_gathering.monitoring import get_logger

log = get_logger("adk.gather")


class GatherAgent(BaseAgent):
    hypothesize_agent: BaseAgent | None = None
    leads_agent: BaseAgent | None = None
    cloud_explore_agent: BaseAgent | None = None
    bank: MemoryBank | None = None
    client: AtlassianClient | None = None

    async def _run_planner(self, ctx, agent, output_key: str) -> dict | None:
        """Run a leaf planner `LlmAgent` under `ctx`; return its validated `output_key` dict."""
        result = None
        try:
            async for ev in agent.run_async(ctx):
                delta = getattr(getattr(ev, "actions", None), "state_delta", None) or {}
                if output_key in delta:
                    result = ctx.session.state[output_key] = delta[output_key]
        except Exception as exc:  # noqa: BLE001 — planning is best-effort; must never break gather
            log.warning("KGA planner %r degraded (%s)", output_key, exc)
        return result

    async def _plan(self, ctx, probe, cloud_on: bool) -> tuple[str, list[str] | None, list[str], CloudExplorePlan | None]:
        """Run the search planners (one that can't reach a model degrades in `_run_planner`);
        return (focus_terms, leads, planner_md, cloud_plan). `cloud_on` gates the cloud planner."""
        terms, leads, planner_md, cloud_plan = probe.terms, None, [], None
        if not probe.title or all(a is None for a in
                                  (self.hypothesize_agent, self.leads_agent, self.cloud_explore_agent)):
            return terms, leads, planner_md, cloud_plan
        ctx.session.state[PLAN_INPUT_KEY] = PlanInput.from_probe(probe).model_dump()
        if self.hypothesize_agent is not None:
            raw = await self._run_planner(ctx, self.hypothesize_agent, HYP_KEY)
            if raw and (hyp := Hypothesis(**raw).as_terms()):
                log.info("A2A gather: hypothesize enriched terms: %r", hyp)
                terms = hyp
                planner_md.append(f"Hypothesized focus: {hyp}")
        if self.leads_agent is not None:
            raw = await self._run_planner(ctx, self.leads_agent, LEADS_KEY)
            leads = Leads(**raw).as_leads() if raw else None
        # X5: cloud re-rank plan — only when the tier is on (grounding-gated in cloud_discover). A no-op
        # when the agent can't reach a model (`_run_planner` swallows it) → numeric rank in discover.
        if self.cloud_explore_agent is not None and cloud_on:
            raw = await self._run_planner(ctx, self.cloud_explore_agent, CLOUD_KEY)
            cloud_plan = CloudExplorePlan(**raw) if raw else None
        return terms, leads, planner_md, cloud_plan

    async def _run_async_impl(self, ctx):
        seed, depth, repo, exclude, explore = parse_input(incoming_text(ctx).strip())
        if not seed:
            yield text_event(self.name, "Provide a seed, e.g. 'gather LUZ-158390 depth 2'.")
            return
        try:
            client, bank = self.client or build_client(), self.bank or build_bank()
        except Exception as exc:  # noqa: BLE001 — missing config/creds → graceful reply
            yield text_event(self.name, f"Config error: {exc}")
            return
        owns_client = self.client is None  # close only the client WE built (injected clients aren't ours)
        try:
            excluded = exclude_ids(exclude)
            extra_seeds = [repo] if repo else []
            probe = await seed_probe(client, seed)
            # NOISY discovery tiers are opt-in (`explore`; the client sets it only after a user Yes):
            # the LLM planners (hypothesize/leads), cloud/system-service discovery, and external
            # web-follow. A plain gather stays quiet + high-precision — Jira/Confluence/codegraph +
            # memory/atlassian-search self-seeding only (the precision=0.00 noise came from these tiers).
            cloud_on = explore and cloud_configured()  # tiers 5/6/7: opt-in AND a provider env map set
            if explore:
                terms, leads, planner_md, cloud_plan = await self._plan(ctx, probe, cloud_on)
            else:
                terms, leads, planner_md, cloud_plan = probe.terms, None, [], None
            new_seeds, md_blocks = await expansion_round(
                bank, client, seed=seed, terms=terms, thin=probe.thin, project=probe.project,
                parent=probe.parent, exclude=excluded | set(extra_seeds), leads=leads,
                explore_cloud=cloud_on, cloud_max_services=cloud_max_services(), cloud_plan=cloud_plan)
            extra_seeds += [s for s in new_seeds if s not in extra_seeds]
            try:
                result = await crawl(client, bank, seed, depth=depth,
                                     scope=Scope(follow_web=True, explore_cloud=cloud_on,
                                                 cloud_max_services=cloud_max_services()),
                                     distiller=None, run_id=ctx.session.id, extra_seeds=extra_seeds or None,
                                     max_seconds=600.0 if repo else 180.0, exclude=excluded)
            except Exception as exc:  # noqa: BLE001 — a crawl/persist failure degrades, never 500s
                log.warning("A2A gather: crawl/persist failed (%s)", exc)
                yield text_event(self.name, f"Gather could not complete: {exc}")
                return
            summary = summarize_gather(result) + "".join(f"\n\n{md}" for md in planner_md + md_blocks)
            if not explore:
                summary += ("\n\nQuiet gather — core sources only (Jira/Confluence/codegraph + memory). "
                            "Re-run with explore=true, after confirming with the user, to add the "
                            "cloud/system-discovery, web-follow, and LLM-planner tiers.")
            capture_gather(bank, context_id=ctx.session.id or seed, seed=seed, result=result)
            yield text_event(self.name, summary)
        finally:
            closer = getattr(client, "aclose", None)
            if owns_client and closer is not None:  # release the httpx pool we opened (no FD leak)
                with contextlib.suppress(Exception):
                    await closer()


def build_gather_agent(name: str = "gather") -> GatherAgent:
    """The gather agent + its three explore planners (D15 / X5) as sub_agents; `client`/`bank` are
    injectable, built lazily by the handler when unset. The cloud planner is a no-op unless a provider
    env map is configured (`cloud_configured()`) + Vertex is reachable (guarded in `_plan`)."""
    hyp, leads, cloud = build_hypothesize_agent(), build_leads_agent(), build_cloud_explore_agent()
    return GatherAgent(name=name, hypothesize_agent=hyp, leads_agent=leads, cloud_explore_agent=cloud,
                       sub_agents=[hyp, leads, cloud])
