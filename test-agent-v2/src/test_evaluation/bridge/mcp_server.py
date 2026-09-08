"""TEV MCP tool definitions — registered on the single MCP gateway (`gateway.mcp_server`).

`register_tools(mcp, session)` binds the read-only evaluator tools to an A2A `BridgeSession`; each
translates to an A2A `message/send`. The per-agent standalone bridge was removed in G2 — the gateway
is the single MCP endpoint; the agent is reached over A2A.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from common.bridge import BridgeSession


def register_tools(mcp: MCPServer, session: BridgeSession) -> dict:
    """Register the TEV domain tools on `mcp`, bound to `session`; return {name: fn}. Unique names."""

    @mcp.tool()
    async def evaluate_pack(context_id: str) -> str:
        """Score the pack a gather/refine produced for `context_id` into a Pack Quality Score.

        Returns the PQS + its components (faithfulness, context precision/recall, relevancy,
        trajectory), the retrieval breakdown (recall/precision/leaked hard-negatives), and any missing
        key entities. Read-only over the shared memory bank. context_id comes from gather_knowledge.
        """
        return (await session.ask(f"evaluate {context_id}", context_id=context_id)).text

    @mcp.tool()
    async def evaluate_plan(context_id: str) -> str:
        """Score the test plan + suite the Test-Plan agent produced for `context_id` into a Test-Plan Score.

        Runs AFTER implement_plan. Returns the TPS + its components (fault detection, brief
        groundedness, coverage, oracle strength, trajectory), the scope breakdown (precision/recall +
        any leaked must-not-scope ids — the define-brief-scoping guard), coverage (AC-recall + matrix
        completeness + uncovered behaviours), oracle-strength distribution, and any placeholder leak.
        Read-only over the shared memory bank. context_id comes from gather_knowledge.
        """
        return (await session.ask(f"evaluate plan {context_id}", context_id=context_id)).text

    return {"evaluate_pack": evaluate_pack, "evaluate_plan": evaluate_plan}
