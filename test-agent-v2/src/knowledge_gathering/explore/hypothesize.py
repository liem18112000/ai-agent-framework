"""Tier-1/2 hypothesize step (roadmap G2) — the search-planning `LlmAgent` (D15).

Model access is ONLY via `common.adk.model.agent_model()` (I8): this module must NOT import the raw
Vertex transport. The planner is an ADK `LlmAgent` with `output_schema=Hypothesis`, so ADK
instructs+validates the structured reply for us — the old JSON-fence stripping + `_coerce_terms`
parser and the `asyncio.to_thread(complete, ...)` offload are gone. The `GatherAgent` drives this
agent through its `ctx`, reads `output_key` from `session.state`, and only enriches when the flag is on
(default OFF → zero LLM calls, I1).
"""

from __future__ import annotations

import os

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext

from common.adk.model import agent_model
from knowledge_gathering.explore.schemas import PLAN_INPUT_KEY, Hypothesis

_FLAG = "KGA_LLM_HYPOTHESIZE"
_MAX_TOKENS = 400
_DESC_CAP = 1000

OUTPUT_KEY = "kga_hypothesis"


def hypothesize_enabled() -> bool:
    """G2 opt-in (default OFF). Exposed so the driving agent can skip the planner entirely."""
    return os.environ.get(_FLAG, "").lower() in ("1", "true", "yes", "on")


def _prompt(title: str, description: str, labels: list[str]) -> str:
    """Prompt for a FEW distinctive search terms as strict JSON — no ids/URLs. Demands rare/precise.

    Verbatim from the pre-D15 `complete()` prompt so behaviour is preserved; only the delivery
    mechanism (ADK `LlmAgent.instruction`) changed.
    """
    lbls = ", ".join(labels) if labels else "(none)"
    return (
        "You are the QA Testing Agent's search-planning step. Given a ticket's title, short "
        "description, and labels, return the MOST distinctive, specific search terms to find "
        "related work in Jira/Confluence and the codebase — key phrases, domain entities, and "
        "subsystem/component names.\n"
        "Return at most ~6 of the MOST distinctive, specific search terms. Prefer rare/precise "
        "terms (proper nouns, code identifiers, unique feature names) over broad generic words. "
        "AVOID generic words like: document, system, data, service, component, module, UI, "
        "frontend, styling, management, validation, mapping, structure. Keep each term 1-2 "
        "words.\n"
        'Return ONLY JSON: {"key_phrases":[...],"entities":[...],"subsystems":[...]}.\n'
        "Do NOT invent ticket ids, issue keys, or URLs — return concepts to search for, not "
        "specific tickets.\n\n"
        f"Title: {title}\n"
        f"Description: {description[:_DESC_CAP] or '(none)'}\n"
        f"Labels: {lbls}\n"
    )


def _instruction(ctx: ReadonlyContext) -> str:
    """ADK `InstructionProvider` — assemble the verbatim prompt from `session.state[PLAN_INPUT_KEY]`.

    Returning a callable makes ADK treat the result as final (`bypass_state_injection=True`), so the
    JSON example braces in the prompt are never mis-read as `{state}` placeholders.
    """
    plan = ctx.state.get(PLAN_INPUT_KEY) or {}
    return _prompt(
        (plan.get("title") or "").strip(),
        (plan.get("description") or "").strip(),
        list(plan.get("labels") or []),
    )


def build_hypothesize_agent(*, model=None, name: str = "hypothesize") -> LlmAgent:
    """The G2 planner as an ADK `LlmAgent(output_schema=Hypothesis)`.

    `model` lets tests inject a fake `BaseLlm`; production leaves it None → `agent_model()` (the
    provider's LiteLlm Claude, I8). When the provider is unconfigured `agent_model()` returns None;
    we fall back to `""` so construction never fails — the planner only runs behind the opt-in flag,
    and tests always inject a fake model.
    """
    return LlmAgent(
        name=name,
        model=model or agent_model(max_tokens=_MAX_TOKENS) or "",
        instruction=_instruction,
        output_schema=Hypothesis,
        output_key=OUTPUT_KEY,
    )
