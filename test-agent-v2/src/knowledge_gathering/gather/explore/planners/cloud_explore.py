"""Tier-5 cloud-explore sub-agent (roadmap X5) — the re-rank/cluster planner `LlmAgent` (D15).

The third explore planner, of the exact `hypothesize`/`leads` shape. Given the ticket, it returns
service-NAME priority hints + clusters, which `cloud_discover.rerank_with_plan` uses to REORDER the
services discovery actually returned. Grounding gate: it emits hints, never authoritative ids, so it
can never add a service that isn't live. Degrades to a no-op (numeric rank) when Vertex is
unconfigured — `_run_planner` swallows the failure just like the other two planners. Provider-neutral:
the hints are plain service names, independent of GCP/AWS/Azure."""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext

from common.adk.model import agent_model
from knowledge_gathering.gather.explore.planners import templates
from knowledge_gathering.gather.explore.planners.schemas import (
    PLAN_INPUT_KEY,
    CloudExplorePlan,
    PlanInput,
)

_MAX_TOKENS = 400
_DESC_CAP = 1000

OUTPUT_KEY = "kga_cloud_plan"


def _prompt(title: str, description: str, labels: list[str]) -> str:
    """Prompt for service-name PRIORITIES/CLUSTERS to rank the ticket's live services — hints only.

    Body served by the prompt store (P6) — editable + versioned; falls back to the template
    compiled into the image when no DB is configured."""
    return templates.render(templates.CLOUD_EXPLORE, title, description[:_DESC_CAP], labels)


def _instruction(ctx: ReadonlyContext) -> str:
    """ADK `InstructionProvider` — assemble the verbatim prompt from `session.state[PLAN_INPUT_KEY]`."""
    plan = PlanInput(**(ctx.state.get(PLAN_INPUT_KEY) or {}))
    return _prompt(plan.title.strip(), plan.description.strip(), plan.labels)


def build_cloud_explore_agent(*, model=None, name: str = "cloud_explore") -> LlmAgent:
    """The X5 planner as an ADK `LlmAgent(output_schema=CloudExplorePlan)`."""
    return LlmAgent(name=name, model=model or agent_model(max_tokens=_MAX_TOKENS) or "",
                     instruction=_instruction, output_schema=CloudExplorePlan, output_key=OUTPUT_KEY)
