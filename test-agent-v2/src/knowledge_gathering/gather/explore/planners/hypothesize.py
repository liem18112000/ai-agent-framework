"""Tier-1/2 hypothesize step (roadmap G2) — the search-planning `LlmAgent` (D15)."""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext

from common.adk.model import agent_model
from knowledge_gathering.gather.explore.planners import templates
from knowledge_gathering.gather.explore.planners.schemas import (
    PLAN_INPUT_KEY,
    Hypothesis,
    PlanInput,
)

_MAX_TOKENS = 400
_DESC_CAP = 1000

OUTPUT_KEY = "kga_hypothesis"


def _prompt(title: str, description: str, labels: list[str]) -> str:
    """Prompt for a FEW distinctive search terms as strict JSON — no ids/URLs. Demands rare/precise.

    Body served by the prompt store (P6) — editable + versioned; falls back to the template
    compiled into the image when no DB is configured."""
    return templates.render(templates.HYPOTHESIZE, title, description[:_DESC_CAP], labels)


def _instruction(ctx: ReadonlyContext) -> str:
    """ADK `InstructionProvider` — assemble the verbatim prompt from `session.state[PLAN_INPUT_KEY]`."""
    plan = PlanInput(**(ctx.state.get(PLAN_INPUT_KEY) or {}))
    return _prompt(plan.title.strip(), plan.description.strip(), plan.labels)


def build_hypothesize_agent(*, model=None, name: str = "hypothesize") -> LlmAgent:
    """The G2 planner as an ADK `LlmAgent(output_schema=Hypothesis)`."""
    return LlmAgent(name=name, model=model or agent_model(max_tokens=_MAX_TOKENS) or "",
                     instruction=_instruction, output_schema=Hypothesis, output_key=OUTPUT_KEY)
