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

    @mcp.tool()
    async def benchmark_run(context_id: str) -> str:
        """Benchmark one run: its cached TEV scores (PQS + TPS + components), computed & saved if missing."""
        return (await session.ask(f"benchmark {context_id}", context_id=context_id)).text

    @mcp.tool()
    async def compare_benchmarks(context_ids: str) -> str:
        """Compare 2+ runs' benchmarks side by side. `context_ids`: space- or comma-separated run ids."""
        return (await session.ask(f"compare-benchmarks {context_ids}")).text

    @mcp.tool()
    async def summarize_benchmarks(k: int = 5) -> str:
        """Summarize the K latest runs' benchmarks (K<10): a table + PQS/TPS mean/min/max/best/worst."""
        return (await session.ask(f"summarize-benchmarks {k}")).text

    return {"evaluate_pack": evaluate_pack, "evaluate_plan": evaluate_plan,
            "benchmark_run": benchmark_run, "compare_benchmarks": compare_benchmarks,
            "summarize_benchmarks": summarize_benchmarks}
