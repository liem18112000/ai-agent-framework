"""Autonomous sub-agents for the Testing-Agent SequentialAgent — one class per module.

Headless steps that auto-answer interrogation with the agent's own recommendations
(`accept_recommendation`); this is the opt-in autonomous path. The gated, client-driven path
(each agent's own router + human confirm-gates) is separate and unchanged.
"""

from __future__ import annotations

from testing_agent.subagents.approve_agent import ApproveAgent
from testing_agent.subagents.define_agent import DefineAgent
from testing_agent.subagents.refine_agent import RefineAgent

__all__ = ["ApproveAgent", "DefineAgent", "RefineAgent"]
