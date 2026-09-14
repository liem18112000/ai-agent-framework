"""AdminRouter dispatch — the admin_agent text-router (offline, no LLM, no DB)."""

from __future__ import annotations

import httpx

import main
from admin_agent.agent import build_root_agent
from common.memory import MemoryBank
from common.store.memory import InMemoryObjectStore
from tests.conftest import drive_adk


def _seeded_bank() -> MemoryBank:
    bank = MemoryBank(InMemoryObjectStore())
    bank.write_refine_state("run-a", {"seed": "LUZ-1", "now": "2026-01-01T00-00-00Z",
                                      "done": True, "pending": []})
    bank.write_understanding("run-a", "confirmed brief")
    return bank


def _patch_bank(monkeypatch, bank: MemoryBank) -> None:
    monkeypatch.setattr("admin_agent.agent.build_bank", lambda: bank)


async def test_router_list_runs(monkeypatch):
    _patch_bank(monkeypatch, _seeded_bank())
    out = await drive_adk(build_root_agent, "list-runs")
    assert "run-a" in out and "LUZ-1" in out


async def test_router_get_run(monkeypatch):
    _patch_bank(monkeypatch, _seeded_bank())
    out = await drive_adk(build_root_agent, "get-run run-a")
    assert "confirmed brief" in out


async def test_router_get_run_needs_context(monkeypatch):
    _patch_bank(monkeypatch, _seeded_bank())
    out = await drive_adk(build_root_agent, "get-run")
    assert "Provide a context id" in out


async def test_router_view_memory_procedural(monkeypatch):
    _patch_bank(monkeypatch, _seeded_bank())
    out = await drive_adk(build_root_agent, "view-memory procedural")
    assert "gather_knowledge" in out and "wipe_all" in out


async def test_router_backup_then_list(monkeypatch):
    _patch_bank(monkeypatch, _seeded_bank())
    assert "Backed up" in await drive_adk(build_root_agent, "backup-memory nightly")
    assert "nightly" in await drive_adk(build_root_agent, "list-backups")


async def test_router_wipe_refuses_without_token(monkeypatch):
    monkeypatch.delenv("GCS_BUCKET", raising=False)  # → required token is the literal "WIPE"
    _patch_bank(monkeypatch, _seeded_bank())
    out = await drive_adk(build_root_agent, "wipe-all")
    assert "REFUSED" in out and "WIPE" in out


async def test_router_wipe_with_token_clears_bank(monkeypatch):
    monkeypatch.delenv("GCS_BUCKET", raising=False)
    bank = _seeded_bank()
    bank.delete_prefix("memory-backups/")  # start clean
    _patch_bank(monkeypatch, bank)
    out = await drive_adk(build_root_agent, "wipe-all WIPE")
    assert "blobs removed" in out
    assert not any(k.startswith("memory/") for k in bank._bucket.store)


async def test_router_unknown_command_shows_usage(monkeypatch):
    _patch_bank(monkeypatch, _seeded_bank())
    out = await drive_adk(build_root_agent, "frobnicate")
    assert "Admin verbs" in out


async def test_admin_agent_serves_a2a_card_via_lifespan(monkeypatch):
    """to_a2a routes attach only at ASGI lifespan startup — wrap the round-trip (per the to_a2a note)."""
    monkeypatch.delenv("A2A_BEARER_TOKEN", raising=False)
    app = main.build_app("admin_agent")
    async with app.router.lifespan_context(app):
        paths = {r.path for r in app.router.routes}
        assert {"/", "/livez", "/readyz", "/.well-known/agent-card.json"} <= paths
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t/") as c:
            assert (await c.get("/livez")).status_code == 200
            card = (await c.get("/.well-known/agent-card.json")).json()
            assert card["name"] == "admin_agent"
