"""A1 — the KGA ADK agent graph, offline, over recorded Atlassian fixtures + FakeBucket."""

from __future__ import annotations

import pytest
from google.genai import types

from common.memory import MemoryBank
from tests.conftest import FakeBucket
from tests.eval.harness import recorded_client, run_gather_offline


async def _run_adk_gather(seed_text: str, ctx_id: str, client, monkeypatch) -> MemoryBank:
    """Drive the ADK KGA router through a Runner with a stable session id (== the pipeline ctx)."""
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService

    import knowledge_gathering.gather.agent as ga
    from knowledge_gathering.agent import build_root_agent

    bank = MemoryBank(FakeBucket())
    monkeypatch.setattr(ga, "build_client", lambda: client)
    monkeypatch.setattr(ga, "build_bank", lambda: bank)
    monkeypatch.setattr("knowledge_gathering.agent.build_bank", lambda: bank)
    monkeypatch.setattr("common.adk.interrogation.build_bank", lambda: bank)
    monkeypatch.setattr("common.adk.tools.build_bank", lambda: bank)

    svc = InMemorySessionService()
    await svc.create_session(app_name="kga", user_id="u", session_id=ctx_id)
    runner = Runner(app_name="kga", agent=build_root_agent(), session_service=svc)

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

    bank._turn = turn
    return bank


@pytest.mark.parametrize("seed,fixture", [("LUZ-501", "eval_rich"), ("LUZ-601", "eval_thin")])
async def test_gather_parity_with_v1(monkeypatch, seed, fixture):
    """ADK GatherAgent persists the same node set as the v1 executor for the same fixture."""
    ctx_id = f"eval-{seed}"
    v1 = run_gather_offline(seed, client=recorded_client(fixture), context_id=ctx_id)
    bank = await _run_adk_gather(f"gather {seed}", ctx_id, recorded_client(fixture), monkeypatch)
    reply = await bank._turn(f"gather {seed}")
    assert "Gather complete" in reply
    graph, _ = bank.load_index()
    v2_nodes = set(graph.nodes.keys())
    assert v2_nodes == v1.node_ids, f"node-set drift v2={v2_nodes} v1={v1.node_ids}"


async def test_router_gather_then_refine_and_reads(monkeypatch):
    """The router: gather → then a live refine pauses & resumes to completion; reads dispatch."""
    seed, ctx_id = "LUZ-501", "eval-LUZ-501"
    bank = await _run_adk_gather(f"gather {seed}", ctx_id, recorded_client("eval_rich"), monkeypatch)
    turn = bank._turn

    assert "Gather complete" in await turn(f"gather {seed}")
    assert "[" in await turn("search-memory") or "No matching" in await turn("search-memory")

    first = await turn(f"refine {ctx_id}")
    assert "Nothing to refine" not in first
    replies = [first]
    for _ in range(6):
        if "Refinement complete" in replies[-1]:
            break
        replies.append(await turn("A"))
    assert any("Refinement complete" in r for r in replies), f"never finalized: {replies}"
    assert bank.read_refine_state(ctx_id).get("done") is True
