"""KGA MCP tool definitions — registered on the single MCP gateway (`gateway.mcp_server`).

`register_tools(mcp, session)` binds the read-only knowledge-gathering tools to an A2A `BridgeSession`
(the gateway supplies one session per agent). Each tool translates to an A2A `message/send`. The
per-agent standalone bridge (its own MCP server + HTTP transport) was removed in G2 — the gateway is
the single MCP endpoint; the agents are reached over A2A.
"""

from __future__ import annotations

import json
import uuid

from mcp.server.mcpserver import MCPServer

from common.bridge import BridgeSession


def register_tools(mcp: MCPServer, session: BridgeSession) -> dict:
    """Register the KGA domain tools on `mcp`, bound to `session`; return {name: fn}.

    Unique names only (no `agent_card`/`send_raw`) so several agents' tool sets compose on one
    gateway MCP server without collisions.
    """

    @mcp.tool()
    async def gather_knowledge(
        seed: str, depth: int = 2, repo: str | None = None, context_id: str | None = None,
        exclude: str | None = None,
    ) -> str:
        """Crawl a Jira issue / Confluence page / URL read-only and distill it to the memory bank.

        seed:       a Jira key (e.g. LUZ-158390), a Confluence page id, or a URL.
        depth:      hops to follow from the seed (default 2).
        repo:       OPTIONAL code repo "<ws>/<repo>" (e.g. axonivy-prod/luz_docs_import). When set,
                    its graphify code graph is (re)built and seeded into the crawl to ground the
                    technical interrogation on real code. Have the user confirm the repo + (re)build
                    before passing it.
        context_id: reuse to tie this crawl to a later refine() session; auto-generated if omitted.
        exclude:    OPTIONAL negative-signal phrase to re-aim a self-exploration that drifted off-topic
                    (e.g. "zip import"). Re-run the SAME context_id with it: matching nodes are pruned
                    from the pack and the focus is steered away, so one human correction re-anchors the
                    loop instead of restarting the gather. Effective on the self-exploration path.

        Returns the crawl summary, prefixed with the context_id to pass to refine().
        """
        ctx = context_id or f"run-{uuid.uuid4().hex[:8]}"
        msg: dict = {"seed": seed, "depth": depth}
        if repo:
            msg["repo"] = repo
        if exclude:
            msg["exclude"] = exclude
        res = await session.ask(json.dumps(msg), context_id=ctx)
        return f"context_id: {ctx}\n\n{res.text}"

    @mcp.tool()
    async def gather_codebase(repo: str, context_id: str | None = None) -> str:
        """Build a graphify code graph for a Bitbucket repo — code-base intelligence for the pack.

        Runs graphify (local, no API key), stores the graph versioned in GCS, and distills a Note
        (REST endpoints, enums, hubs) into the memory bank so refine + the test plan ground on real code.

        repo:       "<workspace>/<repo>" (e.g. axonivy-prod/luz_docs_import) or a bitbucket.org repo URL.
        context_id: reuse to tie this into a gather/refine session; auto-generated if omitted.
        """
        ctx = context_id or f"run-{uuid.uuid4().hex[:8]}"
        res = await session.ask(json.dumps({"seed": repo, "depth": 1}), context_id=ctx)
        return f"context_id: {ctx}\n\n{res.text}"

    @mcp.tool()
    async def refine(context_id: str, answer: str | None = None) -> str:
        """Interrogate a gathered context pack (multi-turn), then restate a confirmed understanding.

        Start with refine(context_id) — the agent replies with the first question round and pauses.
        Answer each round with refine(context_id, answer="Q-biz-1: <your choice>") until the reply
        says 'Refinement complete'. context_id comes from gather_knowledge.

        The client owns the confirm gate: ask the user Yes/No before the first refine call.
        (Server-driven elicitation was removed — Claude Code can't deliver it over remote HTTP, #85442.)
        """
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
        """Search the knowledge index (link graph) in the GCS memory bank.

        Lists matching nodes as `id [type] — title`. Pass a query to filter by id / title / type, or
        omit it to summarize the whole index. Feed an id to get_note. Read-only; spans all gathers.
        """
        return (await session.ask(f"search-memory {query}".strip())).text

    @mcp.tool()
    async def get_note(note_id: str) -> str:
        """Return one distilled note from the memory bank by id, e.g. get_note("jira:LUZ-158390").

        ids come from search_memory. Returns the note's rendered markdown. Read-only.
        """
        return (await session.ask(f"get-note {note_id}")).text

    @mcp.tool()
    async def search_lessons(query: str = "") -> str:
        """List the agent's captured self-learning lessons (all if query omitted). Read-only.

        Lessons are cited facts/corrections the agent recorded from earlier runs. Each row shows its
        id — pass that to veto_lesson to retract a wrong one.
        """
        return (await session.ask(f"search-lessons {query}".strip())).text

    @mcp.tool()
    async def veto_lesson(insight_id: str) -> str:
        """Retract a wrong lesson by id (from search_lessons) — excluded from recall, never re-learned."""
        return (await session.ask(f"veto-lesson {insight_id}")).text

    @mcp.tool()
    async def approve(context_id: str) -> str:
        """Close the refinement loop once YOU are satisfied — the 'approved' exit condition.

        The refine loop lives here in Claude: keep calling refine + get_understanding until the
        restated understanding is right, then approve(context_id). Assembles the final understanding +
        Q/A record as the 'Collect insight' hand-off for the Test-Plan phase and ends the session.
        Read-only; no write back to Atlassian.

        The client owns the confirm gate: ask the user Yes/No before calling approve (#85442).
        """
        understanding = (await session.ask(f"get-understanding {context_id}", context_id=context_id)).text
        questions = (await session.ask(f"get-questions {context_id}", context_id=context_id)).text
        session.tasks.pop(context_id, None)
        return (
            f"APPROVED {context_id}\n\n## Confirmed understanding\n{understanding}\n\n"
            f"## Questions & answers\n{questions}"
        )

    return {
        "gather_knowledge": gather_knowledge, "gather_codebase": gather_codebase, "refine": refine,
        "get_questions": get_questions, "get_understanding": get_understanding,
        "search_memory": search_memory, "get_note": get_note, "search_lessons": search_lessons,
        "veto_lesson": veto_lesson, "approve": approve,
    }
