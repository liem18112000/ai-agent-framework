"""DefineAgent — TPD's methodology/scope/metrics interrogation (Option B)."""

from __future__ import annotations

from common.adk.interrogation import InterrogationAgent, SessionSpec, register_spec
from test_plan_definition import memory as store
from test_plan_definition.define.loop import PlanSession
from test_plan_definition.define_ops import summarize_define
from test_plan_definition.models import ROUNDS

register_spec("plan", SessionSpec(
    make=lambda bank, cid, rounds, now: PlanSession(
        bank, cid, seed=cid, rounds=rounds, run_id=f"plan-{cid[:8]}", now=now),
    rehydrate=lambda bank, cid: PlanSession.rehydrate(bank, cid),
    read_state=lambda bank, cid: store.read_plan_state(bank, cid),
    mark_done=lambda bank, cid: store.write_plan_state(bank, cid, {"done": True}),
    summarize=summarize_define,
))


def build_define_agent(name: str = "define") -> InterrogationAgent:
    return InterrogationAgent(
        name=name,
        rounds=tuple(ROUNDS),
        agent_prefix="TPD",
        header="Test Plan questions — answer each as `Q-id: your choice`.",
        kind="plan",
    )
