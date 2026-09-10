"""Autonomous Testing Agent (E7) — the opt-in end-to-end pipeline."""

from __future__ import annotations

from google.adk.agents import SequentialAgent

from knowledge_gathering.gather.agent import GatherAgent
from test_plan_definition.implement.generate.agent import ImplementAgent
from testing_agent.subagents import ApproveAgent, DefineAgent, RefineAgent


def build_root_agent() -> SequentialAgent:
    return SequentialAgent(
        name="testing_agent",
        description=(
            "Autonomously turns a Jira ticket into a test plan end to end — gather → refine → define "
            "→ approve → implement — auto-answering interrogation rounds with the agent's own "
            "recommendations (no human gates)."
        ),
        sub_agents=[
            GatherAgent(name="gather"),
            RefineAgent(name="refine"),
            DefineAgent(name="define"),
            ApproveAgent(name="approve"),
            ImplementAgent(name="implement"),
        ],
    )


root_agent = build_root_agent()
