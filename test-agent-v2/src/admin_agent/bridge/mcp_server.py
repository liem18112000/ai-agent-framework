"""Admin MCP tool definitions — the [ADMIN — non-pipeline] group on the single MCP gateway.

Six thin forwarders over the admin A2A agent. Every docstring is prefixed so a client can visibly tell
the admin surface from the `gather → … → implement` pipeline; `wipe_all` is destructive and states the
required confirm token.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from common.bridge import BridgeSession


def register_tools(mcp: MCPServer, session: BridgeSession) -> dict:
    """Register the ADMIN utility tools on `mcp`, bound to `session`; return {name: fn}."""

    @mcp.tool()
    async def list_runs(limit: int = 50) -> str:
        """[ADMIN — not part of the testing pipeline] List every past pipeline run, newest first."""
        return (await session.ask(f"list-runs {limit}")).text

    @mcp.tool()
    async def get_run(context_id: str) -> str:
        """[ADMIN — not part of the testing pipeline] Full structured test detail for one run id."""
        return (await session.ask(f"get-run {context_id}", context_id=context_id)).text

    @mcp.tool()
    async def compare_runs(context_a: str, context_b: str) -> str:
        """[ADMIN — not part of the testing pipeline] Diff two runs of the same ticket into COMMON
        (stable across runs — trust it) vs DIVERGENT (only in one — drift / model variance to review),
        across understanding / plan / scenarios / lessons, with a cross-run consensus score."""
        return (await session.ask(f"compare-runs {context_a} {context_b}", context_id=context_a)).text

    @mcp.tool()
    async def view_memory(tier: str = "all", context_id: str | None = None) -> str:
        """[ADMIN — not part of the testing pipeline] View the four memory tiers
        (all|working|episodic|semantic|procedural). `working` needs a context_id."""
        arg = f"view-memory {tier}" + (f" {context_id}" if context_id else "")
        return (await session.ask(arg, context_id=context_id)).text

    @mcp.tool()
    async def backup_memory(summary: str) -> str:
        """[ADMIN — not part of the testing pipeline] Snapshot the memory bank to a timestamped,
        summarised version under memory-backups/ (pgvector is rebuildable, not copied)."""
        return (await session.ask(f"backup-memory {summary}")).text

    @mcp.tool()
    async def list_backups() -> str:
        """[ADMIN — not part of the testing pipeline] List memory-bank backup versions, newest first."""
        return (await session.ask("list-backups")).text

    @mcp.tool()
    async def publish_memory_graph(title: str = "Memory graph") -> str:
        """[ADMIN — not part of the testing pipeline] Render memory_node + memory_edge as a
        self-contained, force-directed HTML page (graphify-style node-link view, coloured by node type,
        drag + hover-for-synopsis). Returns the HTML string — write it to a .html file and publish it
        with the Artifact tool. Reads pgvector when configured, else the GCS knowledge index."""
        return (await session.ask(f"memory-graph {title}".strip())).text

    @mcp.tool()
    async def wipe_all(confirm: str) -> str:
        """[ADMIN — not part of the testing pipeline] DESTRUCTIVE — clears the memory bank, pgvector,
        and the A2A task + ADK session tables in one call. `confirm` MUST equal the GCS_BUCKET value
        (or the literal "WIPE" when unset); the server refuses and echoes the exact token otherwise.
        memory-backups/** always survives. Ask the user Yes/No before calling."""
        return (await session.ask(f"wipe-all {confirm}")).text

    return {
        "list_runs": list_runs, "get_run": get_run, "compare_runs": compare_runs,
        "view_memory": view_memory, "backup_memory": backup_memory,
        "list_backups": list_backups, "publish_memory_graph": publish_memory_graph, "wipe_all": wipe_all,
    }
