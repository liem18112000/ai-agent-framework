"""Autonomous Testing Agent (E7) — the opt-in end-to-end pipeline.

The order is FIXED (gather → refine → define → approve → implement), so the canonical + deterministic
shape is a **SequentialAgent** (like adk-samples/llm-auditor), NOT an LlmAgent+AgentTool coordinator —
no LLM router, determinism preserved (I1). This is a THIRD package that composes the KGA + TPD agents
so neither imports the other (I6). The gated, client-driven path (each agent's own router + human
confirm-gates) is unchanged and remains the default; this is opt-in autonomy for a "test LUZ-xxx"
one-shot.
"""

from __future__ import annotations

from google.adk.agents import SequentialAgent

from knowledge_gathering.agents.gather_agent import GatherAgent
from test_plan_definition.agents.implement_agent import ImplementAgent
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
