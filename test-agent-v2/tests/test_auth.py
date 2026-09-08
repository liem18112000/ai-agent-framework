"""A2A bearer enforcement: card + health open, JSON-RPC gated when A2A_BEARER_TOKEN is set."""

from __future__ import annotations

from starlette.testclient import TestClient


def test_bearer_enforced_when_set(monkeypatch):
    monkeypatch.setenv("A2A_BEARER_TOKEN", "secret")
    from knowledge_gathering.server import app

    c = TestClient(app)
    assert c.get("/.well-known/agent-card.json").status_code == 200
    assert c.get("/livez").status_code == 200

    rpc = {"jsonrpc": "2.0", "id": 1, "method": "nope", "params": {}}
    assert c.post("/", json=rpc).status_code == 401

    ok = c.post("/", headers={"Authorization": "Bearer secret"}, json=rpc)
    assert ok.status_code != 401


def test_no_enforcement_when_unset(monkeypatch):
    monkeypatch.delenv("A2A_BEARER_TOKEN", raising=False)
    from knowledge_gathering.server import app

    c = TestClient(app)
    rpc = {"jsonrpc": "2.0", "id": 1, "method": "nope", "params": {}}
    assert c.post("/", json=rpc).status_code != 401
