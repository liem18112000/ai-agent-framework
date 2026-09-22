"""Register the interrogative-implement SessionSpec and build its InterrogationAgent — the `interrogate`
sub-agent nested under the ImplementOrchestrator. Reuses the shared HITL round loop (Option B)."""

from __future__ import annotations

from common.adk.interrogation import InterrogationAgent, SessionSpec, register_spec
from common.testplan import memory as store
from test_plan_definition.implement.interrogate.session import (
    IMPLEMENT_ROUNDS,
    ImplementBrief,
    ImplementSession,
)


def summarize_implement_interrogation(result: ImplementBrief) -> str:
    kinds = ", ".join(result.kinds) or "happy, negative, boundary, error (defaults)"
    return (f"Implement design confirmed — kinds to cover: {kinds}. "
            f"{len(result.decisions)} design decision(s) recorded; generating artifacts…")


register_spec("implement", SessionSpec(
    make=lambda bank, cid, rounds, now: ImplementSession(
        bank, cid, seed=cid, rounds=rounds, run_id=f"impl-{cid[:8]}", now=now),
    rehydrate=lambda bank, cid: ImplementSession.rehydrate(bank, cid),
    read_state=lambda bank, cid: store.read_implement_state(bank, cid),
    mark_done=lambda bank, cid: store.write_implement_state(bank, cid, {"done": True}),
    summarize=summarize_implement_interrogation,
    pack_of=lambda s: s.plan_pack.pack,  # L4 lesson recall reads the pack off the session
))


def build_interrogate_agent(name: str = "interrogate") -> InterrogationAgent:
    return InterrogationAgent(name=name, rounds=IMPLEMENT_ROUNDS, agent_prefix="TPD",
                             kind="implement",
                             header="Implement design — answer each as `Q-id: your choice`.")
