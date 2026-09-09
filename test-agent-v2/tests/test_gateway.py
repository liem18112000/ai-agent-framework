"""Single MCP gateway tests — one MCP server fronting three A2A agents.

Routing (which tool hits which session, no cross-talk) is proven with a recording fake client;
real A2A interop (to_a2a <-> A2ABridgeClient) is proven once, over an in-process to_a2a app.
"""

from __future__ import annotations

import json

import httpx
import pytest

from common.bridge import A2ABridgeClient
from common.memory import MemoryBank
from common.models import A2AResult
from gateway import mcp_server as gw
from knowledge_gathering.agent import build_root_agent as kga_root
from tests.conftest import _KGA_BANK_TARGETS, FakeBucket, adk_a2a_app, patch_bank


class RecordingClient:
    """A fake A2ABridgeClient: records every send/card call, returns a canned reply."""

    def __init__(self, name: str, reply: str = "ok"):
        self.name, self.reply = name, reply
        self.sent: list[tuple[str, str | None, str | None]] = []
        self.cards = 0

    async def send(self, text, *, context_id=None, task_id=None, message_id=None) -> A2AResult:
        self.sent.append((text, context_id, task_id))
        return A2AResult(text=self.reply, context_id=context_id, task_id=f"t-{self.name}",
                         state="completed", kind="task")

    async def fetch_card(self) -> dict:
        self.cards += 1
        return {"name": self.name, "version": "9.9.9", "skills": [{"id": f"{self.name}-skill"}]}


@pytest.fixture
def wired():
    """Wire a fresh recording client onto each session; tear them all down after."""
    clients = {n: RecordingClient(n) for n in ("kga", "tpd", "tev")}
    gw.kga_session.set_client(clients["kga"])
    gw.tpd_session.set_client(clients["tpd"])
    gw.tev_session.set_client(clients["tev"])
    yield clients
    for s in (gw.kga_session, gw.tpd_session, gw.tev_session):
        s.set_client(None)


async def test_gateway_exposes_union_of_domain_tools_without_collisions():
    names = {t.name for t in await gw.mcp.list_tools()}
    expected = {
        "gather_knowledge", "gather_codebase", "refine", "get_questions", "get_understanding",
        "search_memory", "get_note", "search_lessons", "veto_lesson", "approve",
        "define_plan", "get_plan", "approve_plan", "implement_plan", "get_scenarios",
        "evaluate_pack", "evaluate_plan",
        "agent_cards", "send_raw_kga", "send_raw_tpd", "send_raw_tev",
    }
    assert expected <= names
    assert not ({"send_raw", "agent_card", "plan_card"} & names)


async def test_gather_routes_only_to_kga(wired):
    out = await gw.gather_knowledge("LUZ-501", depth=1, context_id="ctx-g")
    assert wired["kga"].sent and not wired["tpd"].sent and not wired["tev"].sent
    text, ctx, _ = wired["kga"].sent[0]
    assert ctx == "ctx-g" and json.loads(text) == {"seed": "LUZ-501", "depth": 1}
    assert out.startswith("context_id: ctx-g")


async def test_get_plan_routes_only_to_tpd(wired):
    await gw.get_plan("ctx-p")
    assert wired["tpd"].sent == [("get-test-plan ctx-p", "ctx-p", None)]
    assert not wired["kga"].sent and not wired["tev"].sent


async def test_evaluate_pack_routes_only_to_tev(wired):
    await gw.evaluate_pack("ctx-e")
    assert wired["tev"].sent == [("evaluate ctx-e", "ctx-e", None)]
    assert not wired["kga"].sent and not wired["tpd"].sent


async def test_agent_cards_fans_out_to_all_three(wired):
    out = await gw.agent_cards()
    assert all(c.cards == 1 for c in wired.values())
    for name in ("knowledge-gathering", "test-plan-definition", "test-evaluation"):
        assert f"## {name}" in out
    assert "v9.9.9" in out


async def test_a2a_interop_over_to_a2a(monkeypatch):
    """One real round-trip: a to_a2a app answers the bridge client's message/send (routes built on lifespan)."""
    patch_bank(monkeypatch, MemoryBank(FakeBucket()), _KGA_BANK_TARGETS)
    app = adk_a2a_app(kga_root)
    async with app.router.lifespan_context(app):
        client = A2ABridgeClient(base_url="http://agent.test/", transport=httpx.ASGITransport(app=app))
        gw.kga_session.set_client(client)
        try:
            assert "No matching nodes" in await gw.search_memory("")
        finally:
            gw.kga_session.set_client(None)
            await client.aclose()


async def test_gateway_test_prompt_and_instructions():
    prompts = await gw.mcp.list_prompts()
    assert any(p.name == "test" for p in prompts)
    assert "Single MCP gateway" in (gw.mcp.instructions or "")
    assert "TESTING-AGENT TRIGGER" in (gw.mcp.instructions or "")


async def test_gateway_http_app_gated_when_env_set(monkeypatch):
    monkeypatch.setenv("GATEWAY_BEARER_TOKEN", "tok")
    app = gw.http_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t/") as c:
        assert (await c.get("/mcp")).status_code == 401


async def test_gateway_http_app_open_when_env_unset(monkeypatch):
    monkeypatch.delenv("GATEWAY_BEARER_TOKEN", raising=False)
    app = gw.http_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t/") as c:
        assert (await c.get("/livez")).status_code == 200
