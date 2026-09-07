"""M4: A2A -> MCP bridge tests for the test-plan-definition agent.

Drives the bridge's MCP tools against the REAL in-process agent over httpx.ASGITransport
(no network). Reuses the plan A2A app + fake generator from test_plan_a2a so there are no
duplicate fakes.
"""

from __future__ import annotations

import httpx
import pytest
from a2a.server.routes import create_agent_card_routes
from starlette.applications import Starlette
from test_plan_a2a import _app as plan_app

from common.bridge import A2ABridgeClient
from test_plan_definition.a2a_card import AGENT_CARD
from test_plan_definition.bridge import mcp_server as bridge


def _client_for(app) -> A2ABridgeClient:
    return A2ABridgeClient(base_url="http://agent.test/", transport=httpx.ASGITransport(app=app))


@pytest.fixture(autouse=True)
def _reset_bridge():
    yield
    bridge.set_client(None)  # drop injected client + session state between tests


async def test_define_plan_multiturn_tracks_task_and_completes():
    bridge.set_client(_client_for(plan_app()))

    first = await bridge.define_plan("run-6f2a")
    assert "input-required" in first and "Q-mth-1" in first
    assert bridge._tasks.get("run-6f2a")  # task id captured for the continuation

    await bridge.define_plan("run-6f2a", answer="Q-mth-1: API")
    await bridge.define_plan("run-6f2a", answer="Q-sco-1: In scope")
    last = await bridge.define_plan("run-6f2a", answer="Q-mtr-1: End-state verified")

    assert "Plan definition complete" in last
    assert "run-6f2a" not in bridge._tasks  # cleared on completion


async def test_approve_then_implement_then_get_scenarios():
    bridge.set_client(_client_for(plan_app()))
    await bridge.define_plan("run-6f2a")
    await bridge.define_plan("run-6f2a", answer="Q-mth-1: API")
    await bridge.define_plan("run-6f2a", answer="Q-sco-1: In scope")
    await bridge.define_plan("run-6f2a", answer="Q-mtr-1: End-state verified")

    approved = await bridge.approve_plan("run-6f2a")
    assert approved.startswith("APPROVED run-6f2a") and "confirmed" in approved
    assert "run-6f2a" not in bridge._tasks

    done = await bridge.implement_plan("run-6f2a")
    assert "Implement complete" in done

    scenarios = await bridge.get_scenarios("run-6f2a")
    assert "Test Scenarios" in scenarios


async def test_get_plan_before_define_is_graceful():
    bridge.set_client(_client_for(plan_app()))
    out = await bridge.get_plan("run-6f2a")
    assert "No test plan yet" in out


async def test_test_prompt_and_trigger_instructions_shipped_by_server():
    # server-delivered trigger: works on a fresh client with only the MCP connected
    prompts = await bridge.mcp.list_prompts()
    assert any(p.name == "test" for p in prompts)
    assert "TESTING-AGENT TRIGGER" in (bridge.mcp.instructions or "")


async def test_plan_card_lists_skills():
    app = Starlette(routes=create_agent_card_routes(AGENT_CARD))
    bridge.set_client(_client_for(app))
    out = await bridge.plan_card()
    assert "test-plan-definition" in out and "define-test-plan" in out
