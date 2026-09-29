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


# --- the admin router and the admin bridge must not drift apart ---------------------------------
#: Bridge tool names that deliberately differ from their router verb. Keep this map SMALL — it is the
#: escape hatch, and every entry is a place where the two surfaces read differently.
_ADMIN_TOOL_ALIASES = {"memory-graph": "publish_memory_graph"}


async def test_every_admin_verb_is_reachable_over_mcp():
    """A verb on AdminRouter with no bridge tool is a feature nobody can call.

    That is not hypothetical: a08a3d1 added token-usage / token-agents / token-estimate /
    token-lesson to the router and registered none of them, so the whole token-accounting surface
    was unreachable from the gateway — which is the ONLY client-facing surface, the agents being
    A2A-only. The module docstring even says adding a verb is "a new method plus one line here",
    which is the trap. This test is the line that makes that true.
    """
    from admin_agent.agent import root_agent as admin_root

    verbs = set(admin_root._commands())
    names = {t.name for t in await gw.mcp.list_tools()}
    missing = {v for v in verbs if _ADMIN_TOOL_ALIASES.get(v, v.replace("-", "_")) not in names}
    assert not missing, (f"admin verb(s) with no MCP tool: {sorted(missing)} — add a forwarder in "
                         f"admin_agent/bridge/mcp_server.py (or an alias in _ADMIN_TOOL_ALIASES)")


async def test_register_admin_returns_every_tool_it_registered():
    """The returned dict is what `gateway.mcp_server` re-exports via globals(); a tool missing from
    it is registered on MCP but not importable, so tests silently cannot reach it."""
    from admin_agent.agent import root_agent as admin_root

    for verb in admin_root._commands():
        attr = _ADMIN_TOOL_ALIASES.get(verb, verb.replace("-", "_"))
        assert hasattr(gw, attr), f"{attr} not re-exported from gateway.mcp_server"


async def test_token_tools_route_only_to_admin():
    client = RecordingClient("admin")
    gw.admin_session.set_client(client)
    try:
        await gw.token_usage("run-abc")
        await gw.token_estimate("ctx-1", assured_rounds=3)
        await gw.token_agents(["run-a", "run-b"])
        await gw.token_lesson("ctx-1", "drop the pack from the brief prompt")
    finally:
        gw.admin_session.set_client(None)

    sent = [t for t, _c, _t in client.sent]
    assert sent == ["token-usage run-abc", "token-estimate ctx-1 3", "token-agents run-a run-b",
                    "token-lesson ctx-1 drop the pack from the brief prompt"]
    assert client.sent[0][1] == "run-abc"      # run id rides as the context so the task is grouped
    assert client.sent[2][1] is None           # ...but token-agents spans runs, so it has none


async def test_token_usage_with_no_run_id_asks_for_every_run():
    """The bare verb must not be sent as 'token-usage ' with a trailing space — the router partitions
    on the first space and would hand the handler an empty rest either way, but the deployed surface
    is text, so keep it exact."""
    client = RecordingClient("admin")
    gw.admin_session.set_client(client)
    try:
        await gw.token_usage()
    finally:
        gw.admin_session.set_client(None)
    assert client.sent[0][0] == "token-usage"
