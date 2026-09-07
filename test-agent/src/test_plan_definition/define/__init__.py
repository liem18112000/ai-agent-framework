"""Test Plan definition (Stage A) — interrogate methodology/scope/metrics, confirm a TestPlan.

Turn an approved insight pack into a confirmed Test Plan over a multi-turn A2A dialogue,
distilling each human answer into a provenance-carrying PlanDecision and restating a brief the
human reconfirms. Mirrors common.interrogate.
"""

from test_plan_definition.define.decision import assumption_from_self_answer, decision_from_answer
from test_plan_definition.define.loop import PlanResult, PlanSession, define
from test_plan_definition.define.plan import assemble_plan, confidence, restate
from test_plan_definition.define.questions import heuristic_questions, make_generator

__all__ = [
    "PlanResult",
    "PlanSession",
    "assemble_plan",
    "assumption_from_self_answer",
    "confidence",
    "decision_from_answer",
    "define",
    "heuristic_questions",
    "make_generator",
    "restate",
]
