"""TPD MCP tool definitions — registered on the single MCP gateway (`gateway.mcp_server`)."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from common.bridge import BridgeSession


def register_tools(mcp: MCPServer, session: BridgeSession) -> dict:
    """Register the TPD domain tools on `mcp`, bound to `session`; return {name: fn}. Unique names."""

    @mcp.tool()
    async def define_plan(context_id: str, answer: str | None = None) -> str:
        """Interrogate the plan (multi-turn) over methodology / scope / metrics, then confirm it."""
        res = await session.turn(context_id, answer, f"define {context_id}")
        return f"[state: {res.state or 'message'}]\n{res.text}"

    @mcp.tool()
    async def get_plan(context_id: str) -> str:
        """Return the current Test Plan brief for a context id (read-only)."""
        return (await session.ask(f"get-test-plan {context_id}", context_id=context_id)).text

    @mcp.tool()
    async def approve_plan(context_id: str) -> str:
        """Lock the plan to 'confirmed' once YOU are satisfied — the reconfirm gate."""
        res = await session.ask(f"approve {context_id}", context_id=context_id)
        session.tasks.pop(context_id, None)
        return res.text

    @mcp.tool()
    async def implement_plan(context_id: str, detail: bool = False, assured: bool = False) -> str:
        """Generate the test data / scenarios (happy + negative) / steps from the confirmed plan.

        `assured=True` runs the P4 assured loop (generate→judge→gate→reflect→regenerate, opt-in) and
        attaches a quality score to the reply; default is the single-call path."""
        msg = f"implement {context_id}" + (" detail" if detail else "") + (" assured" if assured else "")
        return (await session.ask(msg, context_id=context_id)).text

    @mcp.tool()
    async def get_scenarios(context_id: str) -> str:
        """Return the generated test scenarios + steps for a context id (read-only)."""
        return (await session.ask(f"get-scenarios {context_id}", context_id=context_id)).text

    @mcp.tool()
    async def get_coverage(context_id: str) -> str:
        """Return the Q5 codegraph coverage matrix — requirement×kind traceability + gap report,
        with a code-unit (endpoints/hubs) reached count. Read-only; run implement first."""
        return (await session.ask(f"get-coverage {context_id}", context_id=context_id)).text

    return {"define_plan": define_plan, "get_plan": get_plan, "approve_plan": approve_plan,
           "implement_plan": implement_plan, "get_scenarios": get_scenarios,
           "get_coverage": get_coverage}
