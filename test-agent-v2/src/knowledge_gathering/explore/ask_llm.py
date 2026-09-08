"""Tier-3b external-LLM lead enumerator (roadmap G4) — the lead-generation `LlmAgent` (D15).

Model access is ONLY via `common.adk.model.agent_model()` (I8): this module must NOT import the raw
Vertex transport. The planner is an ADK `LlmAgent` with `output_schema=Leads`, so ADK
instructs+validates the structured reply — the old `_coerce_leads` JSON-array parser and the
`asyncio.to_thread(complete, ...)` offload are gone. The `GatherAgent` drives this agent, reads
`output_key` from `session.state`, then hands the raw phrases to the DETERMINISTIC `ground_leads`
grounding gate (unchanged). Default OFF → zero LLM calls (I1).
"""

from __future__ import annotations

import os

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext

from common.adk.model import agent_model
from knowledge_gathering.explore.schemas import PLAN_INPUT_KEY, Leads

_FLAG = "KGA_LLM_LEADS"
_MAX_TOKENS = 400
_DESC_CAP = 1000

OUTPUT_KEY = "kga_leads"


def leads_enabled() -> bool:
    """G4 opt-in (default OFF). Exposed so the driving agent can skip the planner entirely."""
    return os.environ.get(_FLAG, "").lower() in ("1", "true", "yes", "on")


def _prompt(title: str, description: str, labels: list[str]) -> str:
    """Prompt for speculative LEADS from world knowledge — related work ELSEWHERE, to widen search.

    Wording is verbatim from the pre-D15 `complete()` prompt EXCEPT the final "return shape" line:
    the old prompt asked for a bare JSON array, but `output_schema=Leads` validates an OBJECT
    `{"phrases":[...]}`, so the instruction now names that shape (otherwise a real model's bare-array
    reply would fail validation). The concepts requested are unchanged.
    """
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
    """ADK `InstructionProvider` — assemble the verbatim prompt from `session.state[PLAN_INPUT_KEY]`.

    Returning a callable makes ADK treat the result as final (`bypass_state_injection=True`).
    """
    plan = ctx.state.get(PLAN_INPUT_KEY) or {}
    return _prompt(
        (plan.get("title") or "").strip(),
        (plan.get("description") or "").strip(),
        list(plan.get("labels") or []),
    )


def build_leads_agent(*, model=None, name: str = "leads") -> LlmAgent:
    """The G4 planner as an ADK `LlmAgent(output_schema=Leads)`.

    `model` lets tests inject a fake `BaseLlm`; production leaves it None → `agent_model()` (I8).
    Falls back to `""` when the provider is unconfigured so construction never fails.
    """
    return LlmAgent(
        name=name,
        model=model or agent_model(max_tokens=_MAX_TOKENS) or "",
        instruction=_instruction,
        output_schema=Leads,
        output_key=OUTPUT_KEY,
    )
