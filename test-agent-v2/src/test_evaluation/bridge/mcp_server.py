"""TEV MCP tool definitions — registered on the single MCP gateway (`gateway.mcp_server`)."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from common.bridge import BridgeSession


def register_tools(mcp: MCPServer, session: BridgeSession) -> dict:
    """Register the TEV domain tools on `mcp`, bound to `session`; return {name: fn}. Unique names."""

    @mcp.tool()
    async def evaluate_pack(context_id: str) -> str:
        """Score the pack a gather/refine produced for `context_id` into a Pack Quality Score."""
        return (await session.ask(f"evaluate {context_id}", context_id=context_id)).text

    @mcp.tool()
    async def evaluate_plan(context_id: str) -> str:
        """Score the test plan + suite the Test-Plan agent produced for `context_id` into a Test-Plan Score."""
        return (await session.ask(f"evaluate plan {context_id}", context_id=context_id)).text

    return {"evaluate_pack": evaluate_pack, "evaluate_plan": evaluate_plan}
