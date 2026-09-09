"""Tier-3b external-LLM lead enumerator (roadmap G4) — the lead-generation `LlmAgent` (D15)."""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext

from common.adk.model import agent_model
from knowledge_gathering.gather.explore.planners.schemas import PLAN_INPUT_KEY, Leads, PlanInput

_MAX_TOKENS = 400
_DESC_CAP = 1000

OUTPUT_KEY = "kga_leads"


def _prompt(title: str, description: str, labels: list[str]) -> str:
    """Prompt for speculative LEADS from world knowledge — related work ELSEWHERE, to widen search."""
    lbls = ", ".join(labels) if labels else "(none)"
    return (
        "You are the QA Testing Agent's lead-generation step. Given a ticket's title, short "
        "description, and labels, list related concepts/features/subsystems/edge-cases that "
        "likely have related work elsewhere (in Jira/Confluence/the codebase) for this ticket — "
        "things NOT necessarily stated in it, to widen the search.\n"
        'Return ONLY JSON of the form {"phrases":[...]} with at most ~6 short search phrases '
        "(1-4 words each). Do NOT invent ticket ids, issue keys, or URLs.\n\n"
        f"Title: {title}\n"
        f"Description: {description[:_DESC_CAP] or '(none)'}\n"
        f"Labels: {lbls}\n"
    )


def _instruction(ctx: ReadonlyContext) -> str:
    """ADK `InstructionProvider` — assemble the verbatim prompt from `session.state[PLAN_INPUT_KEY]`."""
    plan = PlanInput(**(ctx.state.get(PLAN_INPUT_KEY) or {}))
    return _prompt(plan.title.strip(), plan.description.strip(), plan.labels)


def build_leads_agent(*, model=None, name: str = "leads") -> LlmAgent:
    """The G4 planner as an ADK `LlmAgent(output_schema=Leads)`."""
    return LlmAgent(
        name=name,
        model=model or agent_model(max_tokens=_MAX_TOKENS) or "",
        instruction=_instruction,
        output_schema=Leads,
        output_key=OUTPUT_KEY,
    )
