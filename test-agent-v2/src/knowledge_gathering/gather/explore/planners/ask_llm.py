"""Tier-3b external-LLM lead enumerator (roadmap G4) — the lead-generation `LlmAgent` (D15)."""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext

from common.adk.model import agent_model
from knowledge_gathering.gather.explore.planners import templates
from knowledge_gathering.gather.explore.planners.schemas import PLAN_INPUT_KEY, Leads, PlanInput

_MAX_TOKENS = 400
_DESC_CAP = 1000

OUTPUT_KEY = "kga_leads"


def _prompt(title: str, description: str, labels: list[str]) -> str:
    """Prompt for speculative LEADS from world knowledge — related work ELSEWHERE, to widen search.

    Body served by the prompt store (P6) — editable + versioned; falls back to the template
    compiled into the image when no DB is configured."""
    return templates.render(templates.LEADS, title, description[:_DESC_CAP], labels)


def _instruction(ctx: ReadonlyContext) -> str:
    """ADK `InstructionProvider` — assemble the verbatim prompt from `session.state[PLAN_INPUT_KEY]`."""
    plan = PlanInput(**(ctx.state.get(PLAN_INPUT_KEY) or {}))
    return _prompt(plan.title.strip(), plan.description.strip(), plan.labels)


def build_leads_agent(*, model=None, name: str = "leads") -> LlmAgent:
    """The G4 planner as an ADK `LlmAgent(output_schema=Leads)`."""
    return LlmAgent(name=name, model=model or agent_model(max_tokens=_MAX_TOKENS) or "",
                     instruction=_instruction, output_schema=Leads, output_key=OUTPUT_KEY)
