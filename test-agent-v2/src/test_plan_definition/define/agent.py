"""DefineAgent — TPD's methodology/scope/metrics interrogation (Option B), plus the `wants_define`
router predicate and the `summarize_define` reply."""

from __future__ import annotations

import json

from common.adk.interrogation import InterrogationAgent, SessionSpec, register_spec
from test_plan_definition import memory as store
from test_plan_definition.define.loop import PlanResult, PlanSession
from test_plan_definition.models import ROUNDS


def wants_define(text: str) -> bool:
    t = text.strip().lower()
    if t.startswith("define"):
        return True
    if t.startswith("{"):
        try:
            return "context_id" in json.loads(text)
        except json.JSONDecodeError:
            return False
    return False


def summarize_define(result: PlanResult) -> str:
    status = result.plan.status if result.plan else "n/a"
    lines = [(f"Plan definition complete (status: {status}, confidence: {result.confidence}). "
              f"{len(result.decisions)} decisions, {len(result.open_gaps)} open gaps."),
             "", result.brief.strip()]
    if result.open_gaps:
        lines += ["", "Declared gaps: " + "; ".join(result.open_gaps)]
    return "\n".join(lines)


register_spec("plan", SessionSpec(
    make=lambda bank, cid, rounds, now: PlanSession(
        bank, cid, seed=cid, rounds=rounds, run_id=f"plan-{cid[:8]}", now=now),
    rehydrate=lambda bank, cid: PlanSession.rehydrate(bank, cid),
    read_state=lambda bank, cid: store.read_plan_state(bank, cid),
    mark_done=lambda bank, cid: store.write_plan_state(bank, cid, {"done": True}),
    summarize=summarize_define,
))


def build_define_agent(name: str = "define") -> InterrogationAgent:
    return InterrogationAgent(name=name, rounds=tuple(ROUNDS), agent_prefix="TPD", kind="plan",
                             header="Test Plan questions — answer each as `Q-id: your choice`.")
