"""Single MCP gateway — one endpoint that fronts the three A2A agents (design G1–G3)."""

from __future__ import annotations

import os

from mcp.server.mcpserver import MCPServer

from admin_agent.bridge.mcp_server import register_tools as register_admin
from common.bridge import BridgeSession, build_http_app
from common.bridge.prompts import TRIGGER_INSTRUCTIONS, test_prompt
from knowledge_gathering.bridge.mcp_server import register_tools as register_kga
from test_evaluation.bridge.mcp_server import register_tools as register_tev
from test_plan_definition.bridge.mcp_server import register_tools as register_tpd

TOKEN = os.environ.get("A2A_BEARER_TOKEN")
KGA_URL = os.environ.get("KGA_A2A_URL", "http://localhost:8081/")
TPD_URL = os.environ.get("TPD_A2A_URL", "http://localhost:8082/")
TEV_URL = os.environ.get("TEV_A2A_URL", "http://localhost:8083/")
ADMIN_URL = os.environ.get("ADMIN_A2A_URL", "http://localhost:8084/")

INSTRUCTIONS = (
    "Single MCP gateway for the Testing Agent — ONE endpoint fronting three A2A agents "
    "(knowledge-gathering, test-plan-definition, test-evaluation). Pipeline: gather_knowledge -> "
    "refine -> approve -> [evaluate_pack] -> define_plan -> approve_plan -> implement_plan -> "
    "get_scenarios -> [evaluate_plan]. Reuse the one context_id gather_knowledge returns for every "
    "later call. YOU (the client) own the confirm gates: before starting refine, approve, "
    "define_plan, approve_plan, and implement_plan, ask the user Yes/No yourself and call the tool "
    "only on yes. evaluate_pack / evaluate_plan are read-only quality gates and never block. "
    "ADMIN / utility group (list_runs, get_run, view_memory, backup_memory, list_backups, wipe_all) "
    "is an operator surface, NOT part of gather -> ... -> implement — never call it as a pipeline "
    "step. wipe_all is DESTRUCTIVE and needs a confirm token (the GCS bucket name, or 'WIPE' when "
    "unset); ask the user Yes/No first, same client-owned-gate convention as the pipeline."
)

kga_session = BridgeSession(KGA_URL, TOKEN)
tpd_session = BridgeSession(TPD_URL, TOKEN)
tev_session = BridgeSession(TEV_URL, TOKEN)
admin_session = BridgeSession(ADMIN_URL, TOKEN)

mcp = MCPServer(
    "testing-agent-gateway", version="0.1.0",
    instructions=INSTRUCTIONS + "\n\n" + TRIGGER_INSTRUCTIONS,
)

_tools = {
    **register_kga(mcp, kga_session),
    **register_tpd(mcp, tpd_session),
    **register_tev(mcp, tev_session),
    **register_admin(mcp, admin_session),
}
globals().update(_tools)

_CARDS = (("knowledge-gathering", kga_session), ("test-plan-definition", tpd_session),
          ("test-evaluation", tev_session), ("admin_agent", admin_session))


@mcp.tool()
async def agent_cards() -> str:
    """Fetch all three agents' A2A cards (name, version, advertised skills)."""
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


@mcp.tool()
async def send_raw_kga(text: str, context_id: str | None = None, task_id: str | None = None) -> str:
    """Escape hatch: send a raw message to the knowledge-gathering agent; return reply + ids + state."""
    return await _raw(kga_session, text, context_id, task_id)


@mcp.tool()
async def send_raw_tpd(text: str, context_id: str | None = None, task_id: str | None = None) -> str:
    """Escape hatch: send a raw message to the test-plan-definition agent; return reply + ids + state."""
    return await _raw(tpd_session, text, context_id, task_id)


@mcp.tool()
async def send_raw_tev(text: str, context_id: str | None = None, task_id: str | None = None) -> str:
    """Escape hatch: send a raw message to the test-evaluation agent; return reply + ids + state."""
    return await _raw(tev_session, text, context_id, task_id)


@mcp.prompt()
def test(jira_key: str = "", depth: str = "2") -> str:
    """Run the full Testing-Agent pipeline for a Jira ticket (gather -> ... -> implement)."""
    return test_prompt(jira_key, depth)


def http_app():
    """Streamable-HTTP ASGI app, gated by GATEWAY_BEARER_TOKEN when set (see common.bridge)."""
    return build_http_app(mcp, "GATEWAY")
