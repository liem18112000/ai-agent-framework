"""main:app — the single per-agent A2A entrypoint (health + bearer gate + ADK-built agent card)."""

from __future__ import annotations

import httpx

import main


async def test_build_app_serves_a2a_health_and_card(monkeypatch):
    monkeypatch.delenv("A2A_BEARER_TOKEN", raising=False)
    app = main.build_app("knowledge_gathering")
    async with app.router.lifespan_context(app):
        paths = {r.path for r in app.router.routes}
        assert {"/", "/livez", "/readyz", "/.well-known/agent-card.json"} <= paths
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t/") as c:
            assert (await c.get("/livez")).status_code == 200
            card = (await c.get("/.well-known/agent-card.json")).json()
            assert card["name"] == "knowledge_gathering"
            assert card["skills"]


async def test_bearer_gate_is_wired(monkeypatch):
    monkeypatch.setenv("A2A_BEARER_TOKEN", "sek")
    app = main.build_app("test_plan_definition")
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t/"
    ) as c:
        assert (await c.get("/livez")).status_code == 200
        assert (await c.post("/", json={})).status_code == 401
