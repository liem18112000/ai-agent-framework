"""A2 — the TPD ADK agent graph, offline: define → approve → implement over a real pack."""

from __future__ import annotations

from google.genai import types

from common.memory import MemoryBank
from common.testplan.models import CONFIRMED


async def _tpd_runner(bank, ctx_id, monkeypatch):
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService

    from test_plan_definition.agent import build_root_agent

    for target in ("common.adk.interrogation.build_bank", "test_plan_definition.agent.build_bank",
                   "test_plan_definition.implement.agent.build_bank"):
        monkeypatch.setattr(target, lambda: bank)

    svc = InMemorySessionService()
    await svc.create_session(app_name="tpd", user_id="u", session_id=ctx_id)
    runner = Runner(app_name="tpd", agent=build_root_agent(), session_service=svc)

    async def turn(text: str) -> str:
        out = []
        async for ev in runner.run_async(
            user_id="u", session_id=ctx_id,
            new_message=types.Content(role="user", parts=[types.Part(text=text)]),
        ):
            c = getattr(ev, "content", None)
            for p in (getattr(c, "parts", None) or []):
                if getattr(p, "text", None) and getattr(c, "role", None) != "user":
                    out.append(p.text)
        return " ".join(out)

    return turn


async def test_define_approve_implement(monkeypatch, pack_bucket):
    ctx_id = "run-6f2a"
    bank = MemoryBank(pack_bucket)
    turn = await _tpd_runner(bank, ctx_id, monkeypatch)

    first = await turn(f"define {ctx_id}")
    assert "Nothing to" not in first, "the fixture pack should be plan-able"
    replies = [first]
    for _ in range(6):
        if "Plan definition complete" in replies[-1]:
            break
        replies.append(await turn("A"))
    assert any("Plan definition complete" in r for r in replies), f"never finalized: {replies}"
    assert len(replies) >= 3, "define should pause/resume across turns"

    approved = await turn(f"approve {ctx_id}")
    assert "APPROVED" in approved
    from common.testplan import memory as store
    assert store.read_plan(bank, ctx_id).status == CONFIRMED

    impl = await turn(f"implement {ctx_id}")
    assert "Implement complete" in impl
    assert "scenarios" in impl
    assert store.read_scenarios_md(bank, ctx_id)
    assert store.read_scenarios_md(bank, ctx_id) in await turn(f"get-scenarios {ctx_id}")


async def test_implement_via_graph_drives_scenario_llm_agent(monkeypatch, pack_bucket):
    """End-to-end through the ADK graph with a fake model: the async ImplementAgent runs the
    ScenarioGen LlmAgent (exactly once — I3) and its structured output reaches persistence."""
    from tests.tpd_fakes import full_fake_model

    ctx_id = "run-6f2a"
    bank = MemoryBank(pack_bucket)
    fake = full_fake_model()
    monkeypatch.setattr("test_plan_definition.implement.llm.agent_model", lambda **k: fake)
    turn = await _tpd_runner(bank, ctx_id, monkeypatch)

    replies = [await turn(f"define {ctx_id}")]
    for _ in range(6):
        if "Plan definition complete" in replies[-1]:
            break
        replies.append(await turn("A"))
    await turn(f"approve {ctx_id}")

    impl = await turn(f"implement {ctx_id}")
    assert "Implement complete" in impl
    assert fake.calls == 1, f"scenario agent must fire exactly once via the graph, fired {fake.calls}"
    from common.testplan import memory as store
    assert "A happy" in (store.read_scenarios_md(bank, ctx_id) or "")
