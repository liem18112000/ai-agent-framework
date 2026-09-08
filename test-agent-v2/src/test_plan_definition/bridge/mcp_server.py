"""TPD MCP tool definitions — registered on the single MCP gateway (`gateway.mcp_server`).

`register_tools(mcp, session)` binds the test-plan-definition tools (define/approve/implement) to an
A2A `BridgeSession`; each translates to an A2A `message/send`. The per-agent standalone bridge was
removed in G2 — the gateway is the single MCP endpoint; the agent is reached over A2A.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from common.bridge import BridgeSession


def register_tools(mcp: MCPServer, session: BridgeSession) -> dict:
    """Register the TPD domain tools on `mcp`, bound to `session`; return {name: fn}. Unique names."""

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
        res = await session.turn(context_id, answer, f"define {context_id}")
        return f"[state: {res.state or 'message'}]\n{res.text}"

    @mcp.tool()
    async def get_plan(context_id: str) -> str:
        """Return the current Test Plan brief for a context id (read-only)."""
        return (await session.ask(f"get-test-plan {context_id}", context_id=context_id)).text

    @mcp.tool()
    async def approve_plan(context_id: str) -> str:
        """Lock the plan to 'confirmed' once YOU are satisfied — the reconfirm gate.

        The define loop lives here in Claude: keep calling define_plan(context_id, answer=…) (and
        get_plan) until the plan brief is right, then approve_plan(context_id). This confirms the
        plan so implement_plan may run, and ends the define session.

        The client owns the confirm gate: ask the user Yes/No before calling approve_plan (elicitation
        was removed — it cannot reach Claude Code over the bridge's remote HTTP transport, #85442).
        """
        res = await session.ask(f"approve {context_id}", context_id=context_id)
        session.tasks.pop(context_id, None)
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
        return (await session.ask(text, context_id=context_id)).text

    @mcp.tool()
    async def get_scenarios(context_id: str) -> str:
        """Return the generated test scenarios + steps for a context id (read-only)."""
        return (await session.ask(f"get-scenarios {context_id}", context_id=context_id)).text

    return {
        "define_plan": define_plan, "get_plan": get_plan, "approve_plan": approve_plan,
        "implement_plan": implement_plan, "get_scenarios": get_scenarios,
    }
