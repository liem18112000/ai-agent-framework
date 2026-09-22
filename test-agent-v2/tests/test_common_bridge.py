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


async def test_turn_sends_answer_after_completed_state():
    """Regression: `to_a2a` interrogation agents finish their invocation each round, so A2A reports
    state='completed' every turn and the task_id is dropped. `turn` must still SEND THE ANSWER on the
    next call (route by answer is not None), not silently re-send start_text and discard the answer —
    which left refine/define_plan advancing rounds while persisting nothing."""
    from common.bridge import BridgeSession
    from common.models import A2AResult

    class _RecordingClient:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send(self, text, *, context_id=None, task_id=None, **kw) -> A2AResult:
            self.sent.append(text)
            return A2AResult(text="ok", context_id=context_id, task_id="t-1", state="completed", kind="task")

    session = BridgeSession("http://agent.test/", None)
    session.set_client(_RecordingClient())
    await session.turn("run-x", None, "refine run-x")            # start
    await session.turn("run-x", "Q-bus-1: yes", "refine run-x")  # human answers
    assert session.get_client().sent == ["refine run-x", "Q-bus-1: yes"]


async def test_ask_raises_on_failed_state_even_when_text_empty():
    """GW-04: a failed A2A task must surface as an error, not return as success with empty text
    (the observed 'malformed / empty response' symptom). All read-only tools route through `ask`."""
    import pytest

    from common.bridge import BridgeSession
    from common.models import A2AResult

    class _FailingClient:
        async def send(self, text, *, context_id=None, task_id=None, **kw) -> A2AResult:
            return A2AResult(text="", context_id=context_id, task_id="t-1", state="failed", kind="task")

    session = BridgeSession("http://agent.test/", None)
    session.set_client(_FailingClient())
    with pytest.raises(RuntimeError, match="agent task failed with no detail"):
        await session.ask("gather run-x", context_id="run-x")


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
