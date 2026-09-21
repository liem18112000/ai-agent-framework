"""Admin MCP tool definitions — the [ADMIN — non-pipeline] group on the single MCP gateway.

Six thin forwarders over the admin A2A agent. Every docstring is prefixed so a client can visibly tell
the admin surface from the `gather → … → implement` pipeline; `wipe_all` is destructive and states the
required confirm token.
"""

from __future__ import annotations

import json

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
    async def record_artifact(context_id: str, kind: str, url: str, title: str = "") -> str:
        """[ADMIN — not part of the testing pipeline] Record a published report artifact URL against a
        run so it can be retrieved later via get_run. Reports are published client-side, so the agent
        never sees the URL unless this records it. `kind` is a free label (knowledge/plan/report);
        the registry is append-only and deduplicated on url."""
        arg = f"record-artifact {context_id} {kind} {url} {title}".rstrip()
        return (await session.ask(arg, context_id=context_id)).text

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
    async def prompt_list() -> str:
        """[ADMIN — not part of the testing pipeline] List every prompt key, the version now serving
        it, and whether that body comes from the database or the image default (version 0)."""
        return (await session.ask("prompt-list")).text

    @mcp.tool()
    async def forget_memory(confirm: str = "") -> str:
        """[ADMIN — not part of the testing pipeline] DESTRUCTIVE — make the agents forget everything
        they have LEARNED: the GCS memory bank and the pgvector recall tier. Narrower than `wipe_all`:
        it does NOT touch A2A tasks, ADK sessions, ADK schema metadata, or the prompt store.

        TWO-PHASE. Call it with no `confirm` first: nothing is deleted and you get a preview of exactly
        what would go plus the required token. ASK THE USER Yes/No with that preview, and only on an
        explicit yes call again with `confirm` set. `memory-backups/**` survives — offer
        `backup_memory` first."""
        return (await session.ask(f"forget-memory {confirm}".strip())).text

    @mcp.tool()
    async def prompt_seed(force: bool = False) -> str:
        """[ADMIN — not part of the testing pipeline] Copy the prompt bodies compiled into the image
        into Postgres as their first version, so the prompts actually in use become visible and
        editable rows. Idempotent: keys already served from the database are skipped. `force=True`
        republishes every key from the current image (use after an image upgrade)."""
        return (await session.ask(f"prompt-seed {'force' if force else ''}".strip())).text

    @mcp.tool()
    async def prompt_get(key: str) -> str:
        """[ADMIN — not part of the testing pipeline] Show the body currently serving `key`, with its
        engine and declared $parameters."""
        return (await session.ask(f"prompt-get {key}")).text

    @mcp.tool()
    async def prompt_publish(key: str, body: str, note: str = "", engine: str = "none") -> str:
        """[ADMIN — not part of the testing pipeline] Publish a NEW version of a prompt body. Validated
        before the write (every $placeholder must be declared), append-only, and it takes effect on the
        next run that refreshes — runs already in flight keep their pinned version."""
        payload = json.dumps({"key": key, "body": body, "note": note, "engine": engine})
        return (await session.ask(f"prompt-publish {payload}")).text

    @mcp.tool()
    async def prompt_rollback(key: str, version: int) -> str:
        """[ADMIN — not part of the testing pipeline] Point `key` back at an earlier version. Nothing
        is deleted — the publish pointer moves, so a bad prompt is a one-call revert."""
        return (await session.ask(f"prompt-rollback {key} {version}")).text

    @mcp.tool()
    async def prompt_history(key: str) -> str:
        """[ADMIN — not part of the testing pipeline] Version log for one prompt key, newest first
        (version, when, by, size, note)."""
        return (await session.ask(f"prompt-history {key}")).text

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
        "list_runs": list_runs, "get_run": get_run, "record_artifact": record_artifact,
        "compare_runs": compare_runs, "view_memory": view_memory, "backup_memory": backup_memory,
        "list_backups": list_backups, "publish_memory_graph": publish_memory_graph, "wipe_all": wipe_all,
    }
