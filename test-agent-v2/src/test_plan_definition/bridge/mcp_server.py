"""The MCP half of the A2A->MCP bridge for the test-plan-definition agent.

Exposes the agent's define/approve/implement skills as MCP tools so an MCP client (Claude)
can drive it. Each tool translates to an A2A `message/send` via a shared BridgeSession (client +
task state + send/turn/card helpers live in common.bridge). Mirrors knowledge_gathering.bridge.

Config (env):
  TPD_A2A_URL        base URL of the agent   (default http://localhost:8081/)
  A2A_BEARER_TOKEN   bearer token, if the agent's BearerAuthMiddleware enforces one

Run:  python -m test_plan_definition.bridge      (stdio transport — how Claude launches it)
"""

from __future__ import annotations

import os

from mcp.server.mcpserver import MCPServer

from common.bridge import BridgeSession, build_http_app
from common.bridge.prompts import TRIGGER_INSTRUCTIONS, test_prompt

BASE_URL = os.environ.get("TPD_A2A_URL", "http://localhost:8081/")
TOKEN = os.environ.get("A2A_BEARER_TOKEN")

mcp = MCPServer(
    "test-plan-definition-bridge",
    version="0.1.0",
    instructions=(
        "Bridge to the test-plan-definition A2A agent (Step 3+4 of the Testing Agent). It "
        "consumes the approved insight pack from knowledge_gathering (the context_id that "
        "approve returned). Flow: define_plan(context_id) starts a methodology/scope/metrics "
        "interrogation and pauses; answer each round with define_plan(context_id, answer=...) "
        "until it reports 'Plan definition complete'. Then approve_plan(context_id) locks the "
        "plan, and implement_plan(context_id) generates the test data / scenarios / steps. "
        "The reconfirm loop lives here in Claude: keep answering (and reading get_plan) until "
        "the plan brief is right, then approve."
    ) + "\n\n" + TRIGGER_INSTRUCTIONS,
)

_session = BridgeSession(BASE_URL, TOKEN)
_tasks = _session.tasks          # exposed for tests
set_client = _session.set_client  # inject an in-process client in tests


@mcp.tool()
async def define_plan(context_id: str, answer: str | None = None) -> str:
    """Interrogate the plan (multi-turn) over methodology / scope / metrics, then confirm it.

    Start with define_plan(context_id) — the agent replies with the first question round and
    pauses. Answer each round with define_plan(context_id, answer="Q-mth-1: <your choice>");
    repeat until the reply says 'Plan definition complete'. context_id comes from
    knowledge_gathering's approve (the "Collect insight" hand-off).

    The client owns the confirm gate: ask the user Yes/No before the first define_plan(context_id)
    call. (Server-driven elicitation was removed — it cannot reach Claude Code over the bridge's
    remote HTTP transport; see issue #85442.)
    """
    res = await _session.turn(context_id, answer, f"define {context_id}")
    return f"[state: {res.state or 'message'}]\n{res.text}"


@mcp.tool()
async def get_plan(context_id: str) -> str:
    """Return the current Test Plan brief for a context id (read-only)."""
    return (await _session.ask(f"get-test-plan {context_id}", context_id=context_id)).text


@mcp.tool()
async def approve_plan(context_id: str) -> str:
    """Lock the plan to 'confirmed' once YOU are satisfied — the reconfirm gate.

    The define loop lives here in Claude: keep calling define_plan(context_id, answer=…) (and
    get_plan) until the plan brief is right, then approve_plan(context_id). This confirms the
    plan so implement_plan may run, and ends the define session.

    The client owns the confirm gate: ask the user Yes/No before calling approve_plan (elicitation
    was removed — it cannot reach Claude Code over the bridge's remote HTTP transport, #85442).
    """
    res = await _session.ask(f"approve {context_id}", context_id=context_id)
    _session.tasks.pop(context_id, None)
    return res.text


@mcp.tool()
async def implement_plan(context_id: str, detail: bool = False) -> str:
    """Generate the test data / scenarios (happy + negative) / steps from the confirmed plan.

    Run this after approve_plan(context_id). Returns a summary; read the full scenarios with
    get_scenarios(context_id).

    detail=False (default) → fast deterministic heuristics (seconds). detail=True → richer but
    slower (~minutes) Claude-generated test data + per-scenario steps; ask the user which they want.

    The client owns the confirm gate: ask the user Yes/No before calling implement_plan (elicitation
    was removed — it cannot reach Claude Code over the bridge's remote HTTP transport, #85442).
    """
    text = f"implement {context_id}" + (" detail" if detail else "")
    return (await _session.ask(text, context_id=context_id)).text


@mcp.tool()
async def get_scenarios(context_id: str) -> str:
    """Return the generated test scenarios + steps for a context id (read-only)."""
    return (await _session.ask(f"get-scenarios {context_id}", context_id=context_id)).text


@mcp.tool()
async def plan_card() -> str:
    """Fetch the agent's A2A card: its name, version, and advertised skills."""
    return await _session.card()


@mcp.tool()
async def send_raw(text: str, context_id: str | None = None, task_id: str | None = None) -> str:
    """Escape hatch: send an arbitrary text message to the agent; return its reply + ids + state."""
    res = await _session.ask(text, context_id=context_id, task_id=task_id)
    return (
        f"[state: {res.state or 'message'}] [context_id: {res.context_id}] "
        f"[task_id: {res.task_id}]\n{res.text}"
    )


@mcp.prompt()
def test(jira_key: str = "", depth: str = "2") -> str:
    """Run the full Testing-Agent pipeline for a Jira ticket (gather -> ... -> implement)."""
    return test_prompt(jira_key, depth)


def http_app():
    """The Streamable-HTTP ASGI app, gated by TPD_BRIDGE_BEARER_TOKEN when set (see common.bridge)."""
    return build_http_app(mcp, "TPD_BRIDGE")
