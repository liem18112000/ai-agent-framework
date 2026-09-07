"""A.0 — the common/adk foundation: imports, model/services/tools/plugins wiring, and the
InterrogationAgent driving the REAL refine engine over a FakeBucket (heuristic, no LLM)."""

from __future__ import annotations

from google.genai import types

from common.adk import (
    InterrogationAgent,
    LearnDrainPlugin,
    LessonRecallPlugin,
    build_session_service,
    claude_llm,
    memory_tools,
)
from common.memory import MemoryBank


# --- model.py (I5/I7) ---
def test_claude_llm_none_without_vertex(monkeypatch):
    monkeypatch.setattr("common.adk.model.vertex_config", lambda: None)
    assert claude_llm() is None  # → callers use the heuristic path


def test_claude_llm_builds_litellm_when_configured(monkeypatch):
    monkeypatch.setattr("common.adk.model.vertex_config", lambda: ("proj", "europe-west6", "claude-sonnet-5"))
    llm = claude_llm(max_tokens=6000)
    assert llm is not None
    assert "claude-sonnet-5" in str(getattr(llm, "model", ""))


# --- services.py ---
def test_session_service_in_memory_without_db(monkeypatch):
    monkeypatch.setattr("common.adk.services.get_engine", lambda: None)
    assert type(build_session_service()).__name__ == "InMemorySessionService"


# --- tools.py (I4 surface) ---
def test_memory_tools_are_bare_callables():
    tools = memory_tools()
    assert all(callable(t) for t in tools)  # bare functions — ADK auto-wraps in tools=[...]
    assert {t.__name__ for t in tools} == {"search_memory", "get_note", "search_lessons", "veto_lesson"}


# --- plugins.py (§6) ---
def test_plugins_construct_with_callbacks():
    assert hasattr(LearnDrainPlugin(), "before_run_callback")
    assert hasattr(LessonRecallPlugin(), "before_model_callback")


# --- interrogation.py (Option B, real engine) ---
async def test_interrogation_agent_pauses_and_resumes_over_real_engine(monkeypatch, pack_bucket):
    """Drive the InterrogationAgent through the reused RefineSession: it must pause per round
    (input round emitted), resume across turns, and finalize — all on the run-6f2a fixture pack."""
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService

    bank = MemoryBank(pack_bucket)
    monkeypatch.setattr("common.adk.interrogation.build_bank", lambda: bank)

    agent = InterrogationAgent(name="refine", rounds=("business", "technical", "qa"), agent_prefix="KGA")
    svc = InMemorySessionService()
    ctx_id = "run-6f2a"  # == the fixture pack's context id
    await svc.create_session(app_name="kga", user_id="u", session_id=ctx_id)
    runner = Runner(app_name="kga", agent=agent, session_service=svc)

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

    first = await turn("start")
    assert "Nothing to refine" not in first, "pack should be non-empty (fixture run-6f2a)"
    # a live (not-done) refine state exists after the first pause → resume is possible
    assert bank.read_refine_state(ctx_id) and not bank.read_refine_state(ctx_id).get("done")

    replies = [first]
    for _ in range(6):
        if "Refinement complete" in replies[-1]:
            break
        replies.append(await turn("A"))  # generic answer; unmatched → carried as gaps, loop still advances

    assert any("Refinement complete" in r for r in replies), f"never finalized: {replies}"
    assert len(replies) >= 3, "should have paused/resumed across multiple turns"
    assert bank.read_refine_state(ctx_id).get("done") is True
    assert bank.read_understanding(ctx_id)  # understanding brief was written
