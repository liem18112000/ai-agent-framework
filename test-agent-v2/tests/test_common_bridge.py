"""common/bridge unit tests — the A2A client + envelope parsing + inbound bearer gate."""

from __future__ import annotations

import httpx
from a2a.server.routes import create_agent_card_routes
from starlette.applications import Starlette
from test_executor_a2a import _app as gather_app

from common.bridge import A2ABridgeClient, extract_text
from common.bridge.asgi import _BearerASGIMiddleware
from knowledge_gathering.a2a_card import AGENT_CARD


def _client_for(app: Starlette) -> A2ABridgeClient:
    """A bridge client whose transport is the given in-process ASGI app (no sockets)."""
    return A2ABridgeClient(base_url="http://agent.test/", transport=httpx.ASGITransport(app=app))


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


async def _ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def test_bearer_middleware_allows_correct_token_rejects_others():
    gated = _BearerASGIMiddleware(_ok_app, "sekret")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gated), base_url="http://t/") as c:
        assert (await c.get("/x", headers={"Authorization": "Bearer sekret"})).status_code == 200
        assert (await c.get("/x")).status_code == 401
        assert (await c.get("/x", headers={"Authorization": "Bearer nope"})).status_code == 401
