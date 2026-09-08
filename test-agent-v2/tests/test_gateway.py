"""Single MCP gateway (G1) tests — one MCP server fronting the three A2A agents."""

from __future__ import annotations

import httpx
import pytest
from starlette.applications import Starlette
from test_executor_a2a import _app as gather_app
from test_plan_a2a import _app as plan_app
from test_refine_a2a import _app as refine_app

from common.bridge import A2ABridgeClient
from gateway import mcp_server as gw


def _client_for(app) -> A2ABridgeClient:
    return A2ABridgeClient(base_url="http://agent.test/", transport=httpx.ASGITransport(app=app))


@pytest.fixture(autouse=True)
def _reset():
    yield
    gw.kga_session.set_client(None)
    gw.tpd_session.set_client(None)
    gw.tev_session.set_client(None)


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


async def test_gateway_routes_gather_to_kga_session():
    gw.kga_session.set_client(_client_for(gather_app()))
    out = await gw.gather_knowledge("LUZ-1", depth=1, context_id="ctx-g")
    assert out.startswith("context_id: ctx-g") and "2 nodes" in out


async def test_gateway_routes_refine_multiturn_to_kga():
    gw.kga_session.set_client(_client_for(refine_app()))
    first = await gw.refine("run-6f2a")
    assert "input-required" in first and "Q-biz-1" in first
    assert gw.kga_session.tasks.get("run-6f2a")


async def test_gateway_routes_define_to_tpd_session():
    gw.tpd_session.set_client(_client_for(plan_app()))
    first = await gw.define_plan("run-6f2a")
    assert "input-required" in first and "Q-mth-1" in first
    assert gw.tpd_session.tasks.get("run-6f2a")


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
    assert isinstance(gw.http_app(), Starlette)
