"""common/bridge unit tests — the A2A client (envelope + normalization), extract_text, bearer gate."""

from __future__ import annotations

import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from common.bridge import A2ABridgeClient, extract_text
from common.bridge.asgi import _BearerASGIMiddleware

_CARD = {"name": "knowledge-gathering", "version": "0.1.0",
         "skills": [{"id": "gather-knowledge"}, {"id": "refine"}]}


def _fake_a2a_app(reply: str = "2 nodes: jira:LUZ-1") -> Starlette:
    """A minimal in-process A2A app: echoes one text message (with contextId) + serves a card."""

    async def rpc(request):
        body = await request.json()
        msg = body["params"]["message"]
        result = {"kind": "message", "messageId": "m1", "contextId": msg.get("contextId"),
                  "parts": [{"kind": "text", "text": reply}]}
        return JSONResponse({"jsonrpc": "2.0", "id": body.get("id"), "result": result})

    async def card(request):
        return JSONResponse(_CARD)

    return Starlette(routes=[Route("/", rpc, methods=["POST"]),
                             Route("/.well-known/agent-card.json", card, methods=["GET"])])


def _client_for(app: Starlette) -> A2ABridgeClient:
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


async def test_client_send_normalizes_message_and_propagates_context():
    async with _client_for(_fake_a2a_app()) as c:
        res = await c.send('{"seed": "LUZ-1", "depth": 1}', context_id="ctx-g")
        assert res.kind == "message"
        assert res.state is None and res.is_complete
        assert res.context_id == "ctx-g"
        assert "jira:LUZ-1" in res.text


async def test_client_fetch_card():
    async with _client_for(_fake_a2a_app()) as c:
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


async def test_bearer_middleware_livez_open():
    gated = _BearerASGIMiddleware(_ok_app, "sekret")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gated), base_url="http://t/") as c:
        r = await c.get("/livez")
        assert r.status_code == 200 and r.json() == {"status": "ok"}


async def test_bearer_middleware_passthrough_when_no_token():
    open_app = _BearerASGIMiddleware(_ok_app, None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=open_app), base_url="http://t/") as c:
        assert (await c.get("/x")).status_code == 200
        assert (await c.get("/livez")).status_code == 200
