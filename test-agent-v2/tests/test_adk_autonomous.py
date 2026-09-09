"""E7 — the autonomous SequentialAgent runs gather→refine→define→approve→implement end to end,"""

from __future__ import annotations

from google.genai import types

from common.memory import MemoryBank
from common.testplan import memory as store
from common.testplan.models import CONFIRMED
from tests.conftest import FakeBucket
from tests.eval.harness import recorded_client


async def test_autonomous_pipeline_end_to_end(monkeypatch):
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService

    import knowledge_gathering.gather.agent as ga
    import test_plan_definition.implement.agent as ia
    import testing_agent.subagents.approve_agent as approve_mod
    import testing_agent.subagents.define_agent as define_mod
    import testing_agent.subagents.refine_agent as refine_mod
    from testing_agent.agent import build_root_agent

    bank = MemoryBank(FakeBucket())
    monkeypatch.setattr(ga, "build_client", lambda: recorded_client("eval_rich"))
    for target in (ga, ia, refine_mod, define_mod, approve_mod):
        monkeypatch.setattr(target, "build_bank", lambda: bank)

    ctx_id = "run-auto"
    svc = InMemorySessionService()
    await svc.create_session(app_name="ta", user_id="u", session_id=ctx_id)
    runner = Runner(app_name="ta", agent=build_root_agent(), session_service=svc)

    steps = []
    async for ev in runner.run_async(
        user_id="u", session_id=ctx_id,
        new_message=types.Content(role="user", parts=[types.Part(text="test LUZ-501")]),
    ):
        c = getattr(ev, "content", None)
        for p in (getattr(c, "parts", None) or []):
            if getattr(p, "text", None) and getattr(c, "role", None) != "user":
                steps.append(p.text)

    joined = " | ".join(steps)
    assert "Gather complete" in joined
    assert "[auto-refine]" in joined
    assert "[auto-define]" in joined
    assert "[auto-approve]" in joined
    assert "Implement complete" in joined

    plan = store.read_plan(bank, ctx_id)
    assert plan is not None and plan.status == CONFIRMED
    assert store.read_scenarios_md(bank, ctx_id)
