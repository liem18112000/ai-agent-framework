"""A2A bearer enforcement (common.adk.auth): health + card open, everything else gated when set."""

from __future__ import annotations

import httpx
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from common.adk.auth import BearerAuthMiddleware


def _app() -> Starlette:
    async def ok(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[
        Route("/", ok, methods=["POST"]),
        Route("/livez", ok),
        Route("/.well-known/agent-card.json", ok),
    ])
    app.add_middleware(BearerAuthMiddleware)
    return app


async def _req(app, path, method="GET", **kw):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t/") as c:
        return await c.request(method, path, **kw)


async def test_bearer_enforced_when_set(monkeypatch):
    monkeypatch.setenv("A2A_BEARER_TOKEN", "secret")
    app = _app()
    assert (await _req(app, "/.well-known/agent-card.json")).status_code == 200
    assert (await _req(app, "/livez")).status_code == 200
    assert (await _req(app, "/", "POST")).status_code == 401
    ok = await _req(app, "/", "POST", headers={"Authorization": "Bearer secret"})
    assert ok.status_code != 401


async def test_no_enforcement_when_unset(monkeypatch):
    monkeypatch.delenv("A2A_BEARER_TOKEN", raising=False)
    assert (await _req(_app(), "/", "POST")).status_code != 401
