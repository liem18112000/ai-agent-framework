"""Single MCP gateway — one endpoint that fronts the three A2A agents (design G1–G3)."""

from __future__ import annotations

import os

from mcp.server.mcpserver import MCPServer

from admin_agent.bridge.mcp_server import register_tools as register_admin
from common.bridge import BridgeSession, build_http_app
from common.bridge.prompts import server_instructions, test_prompt, trigger_instructions
from common.learn.config import _on
from knowledge_gathering.bridge.mcp_server import register_tools as register_kga
from test_evaluation.bridge.mcp_server import register_tools as register_tev
from test_plan_definition.bridge.mcp_server import register_tools as register_tpd

try:  # the test_executor agent is WIP — the gateway still serves the other agents when it's absent
    from test_executor.bridge.mcp_server import register_tools as register_exec
except ModuleNotFoundError:
    register_exec = None

TOKEN = os.environ.get("A2A_BEARER_TOKEN")
KGA_URL = os.environ.get("KGA_A2A_URL", "http://localhost:8081/")
TPD_URL = os.environ.get("TPD_A2A_URL", "http://localhost:8082/")
TEV_URL = os.environ.get("TEV_A2A_URL", "http://localhost:8083/")
ADMIN_URL = os.environ.get("ADMIN_A2A_URL", "http://localhost:8084/")
EXEC_URL = os.environ.get("EXEC_A2A_URL", "http://localhost:8085/")

kga_session = BridgeSession(KGA_URL, TOKEN)
tpd_session = BridgeSession(TPD_URL, TOKEN)
tev_session = BridgeSession(TEV_URL, TOKEN)
admin_session = BridgeSession(ADMIN_URL, TOKEN)
exec_session = BridgeSession(EXEC_URL, TOKEN)


async def _benchmark_on_finish(context_id: str) -> None:
    """Eager-benchmark a run once implement_plan is terminal. Flag default-off; tf sets =1 (services.tf)."""
    if _on("BENCHMARK_ON_FINISH"):
        await tev_session.ask(f"benchmark {context_id}", context_id=context_id)

mcp = MCPServer(
    "testing-agent-gateway", version="0.1.0",
    instructions=server_instructions() + "\n\n" + trigger_instructions(),
)

_tools = {
    **register_kga(mcp, kga_session),
    **register_tpd(mcp, tpd_session, on_finish=_benchmark_on_finish),
    **register_tev(mcp, tev_session),
    **(register_exec(mcp, exec_session) if register_exec else {}),
    **register_admin(mcp, admin_session),
}
globals().update(_tools)

_CARDS = (("knowledge-gathering", kga_session), ("test-plan-definition", tpd_session),
          ("test-evaluation", tev_session), ("test-executor", exec_session),
          ("admin_agent", admin_session))


@mcp.tool()
async def agent_cards() -> str:
    """Fetch every agent's A2A card (name, version, advertised skills)."""
    out = []
    for name, session in _CARDS:
        try:
            out.append(f"## {name}\n{await session.card()}")
        except Exception as exc:  # noqa: BLE001 — one unreachable agent must not hide the others
            out.append(f"## {name}\n(unreachable: {exc})")
    return "\n\n".join(out)


async def _raw(session: BridgeSession, text: str, context_id: str | None, task_id: str | None) -> str:
    res = await session.ask(text, context_id=context_id, task_id=task_id)
    return (f"[state: {res.state or 'message'}] [context_id: {res.context_id}] "
            f"[task_id: {res.task_id}]\n{res.text}")


def _make_send_raw(session: BridgeSession):
    async def send_raw(text: str, context_id: str | None = None, task_id: str | None = None) -> str:
        return await _raw(session, text, context_id, task_id)
    return send_raw


# GW-06: one escape-hatch tool per agent, registered in a loop (identical bodies, distinct sessions).
for _agent, (_session, _label) in {
    "kga": (kga_session, "knowledge-gathering"),
    "tpd": (tpd_session, "test-plan-definition"),
    "tev": (tev_session, "test-evaluation"),
    "exec": (exec_session, "test-executor"),
}.items():
    mcp.tool(
        name=f"send_raw_{_agent}",
        description=f"Escape hatch: send a raw message to the {_label} agent; return reply + ids + state.",
    )(_make_send_raw(_session))


@mcp.prompt()
def test(jira_key: str = "", depth: str = "2") -> str:
    """Run the full Testing-Agent pipeline for a Jira ticket (gather -> ... -> implement)."""
    return test_prompt(jira_key, depth)


def http_app():
    """Streamable-HTTP ASGI app, gated by GATEWAY_BEARER_TOKEN when set (see common.bridge)."""
    return build_http_app(mcp, "GATEWAY")
