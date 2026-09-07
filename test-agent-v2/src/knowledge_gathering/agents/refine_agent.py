"""RefineAgent — KGA's HITL interrogation over rounds business/technical/qa (Option B).

Just the shared InterrogationAgent configured with KGA's rounds; the pause/resume + engine reuse
live in common.adk.interrogation.
"""

from __future__ import annotations

from common.adk.interrogation import InterrogationAgent
from common.models import ROUNDS


def build_refine_agent(name: str = "refine") -> InterrogationAgent:
    return InterrogationAgent(
        name=name,
        rounds=tuple(ROUNDS),  # ("business", "technical", "qa")
        agent_prefix="KGA",
        header="Refinement questions — answer each as `Q-id: your choice`.",
    )
