"""TPD MCP tool definitions — registered on the single MCP gateway (`gateway.mcp_server`)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from mcp.server.mcpserver import MCPServer

from common.bridge import BridgeSession
from common.monitoring import get_logger

log = get_logger("bridge.tpd")


def register_tools(mcp: MCPServer, session: BridgeSession,
                   *, on_finish: Callable[[str], Awaitable[None]] | None = None) -> dict:
    """Register the TPD domain tools on `mcp`, bound to `session`; return {name: fn}. Unique names.

    `on_finish(context_id)` (optional) fires once a run is TERMINAL — implement_plan came back done or
    errored, never on an in_progress chunk. The gateway uses it to eager-benchmark the finished run
    (the bridge stays agent-agnostic — it just calls back)."""

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
    async def implement_plan(context_id: str, detail: bool = False, guidance: str = "") -> str:
        """Generate the test data / scenarios (happy + negative) / steps from the confirmed plan.

        Scenarios always run through the P4 assured loop (generate→judge→gate→reflect→regenerate); the
        reply carries a quality score AND the judge's per-round evaluation + criticism (the reference
        view). If it comes back BELOW BAR, re-invoke with `guidance="<your steer>"` to run another
        round seeded by that steer. `detail=True` also puts test-data + steps on the LLM.

        MULTI-TURN: the loop is chunked so one call stays under the MCP idle timeout. If the reply
        starts `[state: in_progress]`, call implement_plan(context_id) again (no new args) to run the
        next round — repeat until `[state: done]`, then get_scenarios."""
        msg = f"implement {context_id}" + (" detail" if detail else "")
        if guidance:
            msg += f"\nguidance: {guidance}"
        reply = None
        try:
            reply = (await session.ask(msg, context_id=context_id)).text
            return reply
        finally:
            # Run terminal (done or errored — reply is None on an exception), not a paused chunk.
            if on_finish is not None and (reply is None or "[state: in_progress]" not in reply):
                try:
                    await on_finish(context_id)
                except Exception as exc:  # noqa: BLE001 — the benchmark must never break implement's response
                    log.warning("on_finish hook failed for %s: %s", context_id, exc)

    @mcp.tool()
    async def get_scenarios(context_id: str) -> str:
        """Return the generated test scenarios + steps for a context id (read-only)."""
        return (await session.ask(f"get-scenarios {context_id}", context_id=context_id)).text

    @mcp.tool()
    async def get_coverage(context_id: str) -> str:
        """Return the Q5 codegraph coverage matrix — requirement×kind traceability + gap report,
        with a code-unit (endpoints/hubs) reached count. Read-only; run implement first."""
        return (await session.ask(f"get-coverage {context_id}", context_id=context_id)).text

    @mcp.tool()
    async def get_deliverables(context_id: str) -> str:
        """Return the downloadable deliverable payloads for a run — the persisted .feature, the
        test-data fixtures (JSON), and every diagram-as-code (mermaid) — each in its own fenced block
        so the client can render them and offer each as a downloadable file. Read-only; run implement
        first."""
        return (await session.ask(f"get-deliverables {context_id}", context_id=context_id)).text

    return {"define_plan": define_plan, "get_plan": get_plan, "approve_plan": approve_plan,
           "implement_plan": implement_plan, "get_scenarios": get_scenarios,
           "get_coverage": get_coverage, "get_deliverables": get_deliverables}
