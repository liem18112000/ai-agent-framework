"""KGA MCP tool definitions — registered on the single MCP gateway (`gateway.mcp_server`)."""

from __future__ import annotations

import json
import uuid

from mcp.server.mcpserver import MCPServer

from common.bridge import BridgeSession


def register_tools(mcp: MCPServer, session: BridgeSession) -> dict:
    """Register the KGA domain tools on `mcp`, bound to `session`; return {name: fn}."""

    @mcp.tool()
    async def gather_knowledge(
        seed: str, depth: int = 2, repo: str | None = None, context_id: str | None = None,
        exclude: str | None = None, explore: bool = False,
    ) -> str:
        """Crawl a Jira issue / Confluence page / URL read-only and distill it to the memory bank.

        Default gather is QUIET + high-precision: core sources only (Jira/Confluence/codegraph + memory
        recall). Set explore=True — ONLY after asking the user Yes — to also run the noisy discovery
        tiers: cloud/system-service discovery, external web-follow, and the LLM planners (hypothesize /
        leads). These are what drive down retrieval precision, so they stay opt-in per the user gate."""
        ctx = context_id or f"run-{uuid.uuid4().hex[:8]}"
        msg: dict = {"seed": seed, "depth": depth, **({"repo": repo} if repo else {}),
                     **({"exclude": exclude} if exclude else {}), **({"explore": True} if explore else {})}
        return f"context_id: {ctx}\n\n{(await session.ask(json.dumps(msg), context_id=ctx)).text}"

    @mcp.tool()
    async def gather_codebase(repo: str, context_id: str | None = None) -> str:
        """Build a graphify code graph for a Bitbucket repo — code-base intelligence for the pack."""
        ctx = context_id or f"run-{uuid.uuid4().hex[:8]}"
        return f"context_id: {ctx}\n\n{(await session.ask(json.dumps({'seed': repo, 'depth': 1}), context_id=ctx)).text}"

    @mcp.tool()
    async def refine(context_id: str, answer: str | None = None) -> str:
        """Interrogate a gathered context pack (multi-turn), then restate a confirmed understanding."""
        res = await session.turn(context_id, answer, f"refine {context_id}")
        return f"[state: {res.state or 'message'}]\n{res.text}"

    @mcp.tool()
    async def get_questions(context_id: str) -> str:
        """Return the current open/answered refinement questions for a context id (read-only)."""
        return (await session.ask(f"get-questions {context_id}", context_id=context_id)).text

    @mcp.tool()
    async def get_understanding(context_id: str) -> str:
        """Return the latest restated understanding brief for a context id (read-only)."""
        return (await session.ask(f"get-understanding {context_id}", context_id=context_id)).text

    @mcp.tool()
    async def search_memory(query: str = "") -> str:
        """Search the knowledge index (link graph) in the GCS memory bank."""
        return (await session.ask(f"search-memory {query}".strip())).text

    @mcp.tool()
    async def get_note(note_id: str) -> str:
        """Return one distilled note from the memory bank by id, e.g. get_note("jira:LUZ-158390")."""
        return (await session.ask(f"get-note {note_id}")).text

    @mcp.tool()
    async def search_lessons(query: str = "") -> str:
        """List the agent's captured self-learning lessons (all if query omitted). Read-only."""
        return (await session.ask(f"search-lessons {query}".strip())).text

    @mcp.tool()
    async def veto_lesson(insight_id: str) -> str:
        """Retract a wrong lesson by id (from search_lessons) — excluded from recall, never re-learned."""
        return (await session.ask(f"veto-lesson {insight_id}")).text

    @mcp.tool()
    async def approve(context_id: str) -> str:
        """Close the refinement loop once YOU are satisfied — the 'approved' exit condition."""
        understanding = (await session.ask(f"get-understanding {context_id}", context_id=context_id)).text
        questions = (await session.ask(f"get-questions {context_id}", context_id=context_id)).text
        session.tasks.pop(context_id, None)
        return f"APPROVED {context_id}\n\n## Confirmed understanding\n{understanding}\n\n## Questions & answers\n{questions}"

    return {
        "gather_knowledge": gather_knowledge, "gather_codebase": gather_codebase, "refine": refine,
        "get_questions": get_questions, "get_understanding": get_understanding,
        "search_memory": search_memory, "get_note": get_note, "search_lessons": search_lessons,
        "veto_lesson": veto_lesson, "approve": approve,
    }
