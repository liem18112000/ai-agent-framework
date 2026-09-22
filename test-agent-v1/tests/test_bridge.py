"""A2A -> MCP bridge tests.

Drives the bridge's A2A client and MCP tools against the REAL in-process agent over
httpx.ASGITransport (no network). App builders are reused from the existing A2A tests so
there are no duplicate fakes; the refine builder pulls the `pack_run-6f2a` fixture via conftest.
"""

from __future__ import annotations

import httpx
import pytest
from a2a.server.routes import create_agent_card_routes
from starlette.applications import Starlette

# reuse the real agent apps + fake generator from the existing A2A integration tests
from test_executor_a2a import _app as gather_app
from test_refine_a2a import _app as refine_app

from common.bridge.asgi import _BearerASGIMiddleware
from knowledge_gathering.agent import AGENT_CARD
from knowledge_gathering.bridge import A2ABridgeClient, extract_text
from knowledge_gathering.bridge import mcp_server as bridge


def _client_for(app: Starlette) -> A2ABridgeClient:
    """A bridge client whose transport is the given in-process ASGI app (no sockets)."""
    return A2ABridgeClient(
        base_url="http://agent.test/", transport=httpx.ASGITransport(app=app)
    )


# --- pure translation: extract_text over the two real envelope shapes --- #

def test_extract_text_message_shape():
    result = {"kind": "message", "parts": [{"kind": "text", "text": "hello"}]}
    assert extract_text(result) == "hello"


def test_extract_text_task_status_shape():
    result = {
        "kind": "task",
        "status": {"state": "input-required",
                   "message": {"parts": [{"kind": "text", "text": "a question?"}]}},
    }
    assert extract_text(result) == "a question?"


def test_extract_text_dedupes_and_joins():
    result = {"parts": [{"kind": "text", "text": "x"}, {"kind": "text", "text": "x"},
                        {"kind": "text", "text": "y"}]}
    assert extract_text(result) == "x\ny"


# --- A2A client round-trips against the real agent --- #

async def test_client_gather_returns_message():
    async with _client_for(gather_app()) as c:
        res = await c.send('{"seed": "LUZ-1", "depth": 1}', context_id="ctx-g")
        assert res.kind == "message"
        assert res.state is None and res.is_complete
        assert "2 nodes" in res.text and "jira:LUZ-1" in res.text


async def test_client_missing_seed_replies_helpfully():
    async with _client_for(gather_app()) as c:
        res = await c.send("hello there")
        assert "Provide a seed" in res.text


async def test_client_fetch_card():
    app = Starlette(routes=create_agent_card_routes(AGENT_CARD))
    async with _client_for(app) as c:
        card = await c.fetch_card()
        assert card["name"] == "knowledge-gathering"
        assert any(s["id"] == "gather-knowledge" for s in card["skills"])


# --- MCP tools (injected client) --- #

@pytest.fixture(autouse=True)
def _reset_bridge():
    yield
    bridge.set_client(None)  # drop injected client + session state between tests


async def test_tool_gather_knowledge_prefixes_context_id():
    bridge.set_client(_client_for(gather_app()))
    out = await bridge.gather_knowledge("LUZ-1", depth=1, context_id="ctx-g")
    assert out.startswith("context_id: ctx-g")
    assert "2 nodes" in out


async def test_tool_refine_multiturn_tracks_task_and_completes():
    bridge.set_client(_client_for(refine_app()))

    first = await bridge.refine("run-6f2a")
    assert "input-required" in first and "Q-biz-1" in first
    assert bridge._tasks.get("run-6f2a")  # task id captured for the continuation

    await bridge.refine("run-6f2a", answer="Q-biz-1: Materialized")
    await bridge.refine("run-6f2a", answer="Q-tech-1: dev")
    last = await bridge.refine("run-6f2a", answer="Q-qa-1: happy")

    assert "Refinement complete" in last
    assert "run-6f2a" not in bridge._tasks  # cleared on completion


async def test_tool_approve_returns_understanding_and_clears_session():
    bridge.set_client(_client_for(refine_app()))
    await bridge.refine("run-6f2a")
    await bridge.refine("run-6f2a", answer="Q-biz-1: Materialized")
    await bridge.refine("run-6f2a", answer="Q-tech-1: dev")
    await bridge.refine("run-6f2a", answer="Q-qa-1: happy")

    out = await bridge.approve("run-6f2a")
    assert out.startswith("APPROVED run-6f2a")
    assert "Confirmed understanding" in out
    assert "run-6f2a" not in bridge._tasks


async def test_test_prompt_and_trigger_instructions_shipped_by_server():
    # server-delivered trigger: a fresh client (only MCP connected) sees the /test prompt
    prompts = await bridge.mcp.list_prompts()
    assert any(p.name == "test" for p in prompts)
    assert "TESTING-AGENT TRIGGER" in (bridge.mcp.instructions or "")


async def test_tool_agent_card_lists_skills():
    app = Starlette(routes=create_agent_card_routes(AGENT_CARD))
    bridge.set_client(_client_for(app))
    out = await bridge.agent_card()
    assert "knowledge-gathering" in out and "gather-knowledge" in out


# --- inbound bearer gate on the HTTP transport --- #

async def _ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def test_bearer_middleware_allows_correct_token_rejects_others():
    gated = _BearerASGIMiddleware(_ok_app, "sekret")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gated), base_url="http://t/") as c:
        assert (await c.get("/x", headers={"Authorization": "Bearer sekret"})).status_code == 200
        assert (await c.get("/x")).status_code == 401                                  # missing
        assert (await c.get("/x", headers={"Authorization": "Bearer nope"})).status_code == 401  # wrong


async def test_http_app_gated_when_env_set(monkeypatch):
    monkeypatch.setenv("KGA_BRIDGE_BEARER_TOKEN", "tok")
    app = bridge.http_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t/") as c:
        assert (await c.get("/mcp")).status_code == 401  # gate rejects before the MCP app


async def test_http_app_open_when_env_unset(monkeypatch):
    monkeypatch.delenv("KGA_BRIDGE_BEARER_TOKEN", raising=False)
    app = bridge.http_app()
    assert isinstance(app, Starlette)  # no wrapper → the raw MCP Starlette app


# --- memory read tools (search_memory / get_note) --- #

async def test_tools_search_memory_and_get_note():
    from test_memory_read_a2a import _seeded_bucket  # a bank with one 'jira:LUZ-1' note

    bridge.set_client(_client_for(refine_app(bucket=_seeded_bucket())))

    listed = await bridge.search_memory("login")
    assert "jira:LUZ-1" in listed and "jira-issue" in listed

    note = await bridge.get_note("jira:LUZ-1")
    assert "jira:LUZ-1" in note and "Login bug" in note
