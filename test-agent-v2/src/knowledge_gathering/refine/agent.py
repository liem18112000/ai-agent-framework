"""RefineAgent — KGA's HITL interrogation over rounds business/technical/qa (Option B), plus the
`wants_refine` dispatch predicate the router uses to route to it."""

from __future__ import annotations

import json

from common.adk.interrogation import InterrogationAgent
from common.models import ROUNDS


def wants_refine(text: str) -> bool:
    t = text.strip().lower()
    if t.startswith("refine"):
        return True
    if t.startswith("{"):
        try:
            d = json.loads(text)
        except json.JSONDecodeError:
            return False
        return "context_id" in d or "answers" in d
    return False


def build_refine_agent(name: str = "refine") -> InterrogationAgent:
    return InterrogationAgent(
        name=name,
        rounds=tuple(ROUNDS),
        agent_prefix="KGA",
        header="Refinement questions — answer each as `Q-id: your choice`.",
    )
