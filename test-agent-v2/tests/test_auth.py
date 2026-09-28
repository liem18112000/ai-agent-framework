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


async def test_token_set_correct_bearer_passes(monkeypatch):
    monkeypatch.setenv("A2A_BEARER_TOKEN", "secret")
    ok = await _req(_app(), "/", "POST", headers={"Authorization": "Bearer secret"})
    assert ok.status_code != 401


async def test_token_set_wrong_bearer_401(monkeypatch):
    monkeypatch.setenv("A2A_BEARER_TOKEN", "secret")
    app = _app()
    assert (await _req(app, "/", "POST")).status_code == 401  # missing header
    assert (await _req(app, "/", "POST", headers={"Authorization": "Bearer nope"})).status_code == 401


async def test_fail_closed_when_token_unset_and_not_insecure(monkeypatch):
    """SEC-1: no expected token AND no ALLOW_INSECURE escape hatch → refuse every non-open route."""
    monkeypatch.delenv("A2A_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("ALLOW_INSECURE", raising=False)  # override the conftest session default
    assert (await _req(_app(), "/", "POST")).status_code == 401


async def test_permissive_when_token_unset_and_insecure_opt_in(monkeypatch):
    """No expected token but ALLOW_INSECURE=1 → local/dev passes through."""
    monkeypatch.delenv("A2A_BEARER_TOKEN", raising=False)
    monkeypatch.setenv("ALLOW_INSECURE", "1")
    assert (await _req(_app(), "/", "POST")).status_code != 401


async def test_open_paths_never_gated(monkeypatch):
    """Health + agent-card discovery stay open even fail-closed (token unset, no ALLOW_INSECURE)."""
    monkeypatch.delenv("A2A_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("ALLOW_INSECURE", raising=False)
    assert (await _req(_app(), "/livez")).status_code == 200
    assert (await _req(_app(), "/.well-known/agent-card.json")).status_code == 200
