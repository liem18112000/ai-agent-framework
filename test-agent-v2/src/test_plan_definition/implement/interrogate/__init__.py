"""Interrogate sub-agent — the case-design / data-design / step-oracle interrogation (ImplementSession),
nested under the ImplementOrchestrator; its answers set the plan's open test_kinds before generation."""

from test_plan_definition.implement.interrogate.agent import build_interrogate_agent
from test_plan_definition.implement.interrogate.session import ImplementBrief, ImplementSession

__all__ = ["ImplementBrief", "ImplementSession", "build_interrogate_agent"]
