"""The MCP half of the A2A->MCP bridge for the test-evaluation agent.

Exposes the read-only evaluator as MCP tools; each translates to an A2A `message/send` via a shared
BridgeSession (see common.bridge).

Config (env):
  TEV_A2A_URL        agent base URL (default http://localhost:8080/)
  A2A_BEARER_TOKEN   bearer token, if the agent enforces one

Run:  python -m test_evaluation.bridge      (stdio transport)
"""

from __future__ import annotations

import os

from mcp.server.mcpserver import MCPServer

from common.bridge import BridgeSession, build_http_app

BASE_URL = os.environ.get("TEV_A2A_URL", "http://localhost:8080/")
TOKEN = os.environ.get("A2A_BEARER_TOKEN")

mcp = MCPServer(
    "test-evaluation-bridge",
    version="0.1.0",
    instructions=(
        "Bridge to the read-only test-evaluation A2A agent (Step 5 of the Testing Agent). Two tools, "
        "both read-only over the shared memory bank and both reusing any golden case whose seed "
        "matches the context id:\n"
        "- evaluate_pack(context_id): after a gather/refine, score the PACK — retrieval "
        "precision/recall (hard-negative leak gate), groundedness rubrics, entity coverage — into a "
        "Pack Quality Score (PQS).\n"
        "- evaluate_plan(context_id): after implement_plan, score the TEST PLAN + SUITE — scope "
        "precision/recall (must-not-scope leak gate), coverage adequacy (AC-recall + matrix "
        "completeness + traceability), oracle strength + fault-class coverage, and brief "
        "groundedness — into a Test-Plan Score (TPS)."
    ),
)

_session = BridgeSession(BASE_URL, TOKEN)
_tasks = _session.tasks          # for tests
set_client = _session.set_client  # inject an in-process client in tests


@mcp.tool()
async def evaluate_pack(context_id: str) -> str:
    """Score the pack a gather/refine produced for `context_id` into a Pack Quality Score.

    Returns the PQS + its components (faithfulness, context precision/recall, relevancy,
    trajectory), the retrieval breakdown (recall/precision/leaked hard-negatives), and any missing
    key entities. Read-only over the shared memory bank. context_id comes from gather_knowledge.
    """
    return (await _session.ask(f"evaluate {context_id}", context_id=context_id)).text


@mcp.tool()
async def evaluate_plan(context_id: str) -> str:
    """Score the test plan + suite the Test-Plan agent produced for `context_id` into a Test-Plan Score.

    Runs AFTER implement_plan. Returns the TPS + its components (fault detection, brief
    groundedness, coverage, oracle strength, trajectory), the scope breakdown (precision/recall +
    any leaked must-not-scope ids — the define-brief-scoping guard), coverage (AC-recall + matrix
    completeness + uncovered behaviours), oracle-strength distribution, and any placeholder leak.
    Read-only over the shared memory bank. context_id comes from gather_knowledge.
    """
    return (await _session.ask(f"evaluate plan {context_id}", context_id=context_id)).text


@mcp.tool()
async def agent_card() -> str:
    """Fetch the agent's A2A card: its name, version, and advertised skills."""
    return await _session.card()


@mcp.tool()
async def send_raw(text: str, context_id: str | None = None, task_id: str | None = None) -> str:
    """Escape hatch: send an arbitrary text message to the agent; return its reply + ids + state."""
    res = await _session.ask(text, context_id=context_id, task_id=task_id)
    return (f"[state: {res.state or 'message'}] [context_id: {res.context_id}] "
            f"[task_id: {res.task_id}]\n{res.text}")


def http_app():
    """Streamable-HTTP ASGI app, gated by TEV_BRIDGE_BEARER_TOKEN when set (see common.bridge)."""
    return build_http_app(mcp, "TEV_BRIDGE")
