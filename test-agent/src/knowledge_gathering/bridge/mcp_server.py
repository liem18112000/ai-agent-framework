"""The MCP half of the A2A->MCP bridge.

Exposes the read-only knowledge-gathering A2A agent as MCP tools. Each tool translates to an
A2A `message/send` via a shared BridgeSession (see common.bridge).

Config (env):
  KGA_A2A_URL        agent base URL (default http://localhost:8080/)
  A2A_BEARER_TOKEN   bearer token, if the agent enforces one

Run:  python -m knowledge_gathering.bridge      (stdio transport)
"""

from __future__ import annotations

import json
import os
import uuid

from mcp.server.mcpserver import MCPServer

from common.bridge import BridgeSession, build_http_app
from common.bridge.prompts import TRIGGER_INSTRUCTIONS, test_prompt

BASE_URL = os.environ.get("KGA_A2A_URL", "http://localhost:8080/")
TOKEN = os.environ.get("A2A_BEARER_TOKEN")

mcp = MCPServer(
    "knowledge-gathering-bridge",
    version="0.1.0",
    instructions=(
        "Bridge to the read-only Atlassian knowledge-gathering A2A agent (Step 1 of the "
        "Testing Agent). Typical flow: call gather_knowledge(seed) — it crawls Jira/Confluence "
        "and returns a context_id — then refine(context_id) to interrogate the pack, answering "
        "each round with refine(context_id, answer=...) until it reports 'Refinement complete'. "
        "After gather_knowledge returns, do NOT call refine automatically: first show the gather "
        "summary, then ask the user an explicit Yes/No question (using the client's interactive "
        "question/dialog UI when one is available) whether to refine now, and call refine only "
        "once the user confirms."
    ) + "\n\n" + TRIGGER_INSTRUCTIONS,
)

_session = BridgeSession(BASE_URL, TOKEN)
_tasks = _session.tasks          # for tests
set_client = _session.set_client  # inject an in-process client in tests


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
    res = await _session.ask(json.dumps(msg), context_id=ctx)
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
    res = await _session.ask(json.dumps({"seed": repo, "depth": 1}), context_id=ctx)
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
    res = await _session.turn(context_id, answer, f"refine {context_id}")
    return f"[state: {res.state or 'message'}]\n{res.text}"


@mcp.tool()
async def get_questions(context_id: str) -> str:
    """Return the current open/answered refinement questions for a context id (read-only)."""
    return (await _session.ask(f"get-questions {context_id}", context_id=context_id)).text


@mcp.tool()
async def get_understanding(context_id: str) -> str:
    """Return the latest restated understanding brief for a context id (read-only)."""
    return (await _session.ask(f"get-understanding {context_id}", context_id=context_id)).text


@mcp.tool()
async def search_memory(query: str = "") -> str:
    """Search the knowledge index (link graph) in the GCS memory bank.

    Lists matching nodes as `id [type] — title`. Pass a query to filter by id / title / type, or
    omit it to summarize the whole index. Feed an id to get_note. Read-only; spans all gathers.
    """
    return (await _session.ask(f"search-memory {query}".strip())).text


@mcp.tool()
async def get_note(note_id: str) -> str:
    """Return one distilled note from the memory bank by id, e.g. get_note("jira:LUZ-158390").

    ids come from search_memory. Returns the note's rendered markdown. Read-only.
    """
    return (await _session.ask(f"get-note {note_id}")).text


@mcp.tool()
async def search_lessons(query: str = "") -> str:
    """List the agent's captured self-learning lessons (all if query omitted). Read-only.

    Lessons are cited facts/corrections the agent recorded from earlier runs. Each row shows its
    id — pass that to veto_lesson to retract a wrong one.
    """
    return (await _session.ask(f"search-lessons {query}".strip())).text


@mcp.tool()
async def veto_lesson(insight_id: str) -> str:
    """Retract a wrong lesson by id (from search_lessons) — excluded from recall, never re-learned."""
    return (await _session.ask(f"veto-lesson {insight_id}")).text


@mcp.tool()
async def approve(context_id: str) -> str:
    """Close the refinement loop once YOU are satisfied — the 'approved' exit condition.

    The refine loop lives here in Claude: keep calling refine + get_understanding until the
    restated understanding is right, then approve(context_id). Assembles the final understanding +
    Q/A record as the 'Collect insight' hand-off for the Test-Plan phase and ends the session.
    Read-only; no write back to Atlassian.

    The client owns the confirm gate: ask the user Yes/No before calling approve (#85442).
    """
    understanding = (await _session.ask(f"get-understanding {context_id}", context_id=context_id)).text
    questions = (await _session.ask(f"get-questions {context_id}", context_id=context_id)).text
    _session.tasks.pop(context_id, None)
    return (
        f"APPROVED {context_id}\n\n## Confirmed understanding\n{understanding}\n\n"
        f"## Questions & answers\n{questions}"
    )


@mcp.tool()
async def agent_card() -> str:
    """Fetch the agent's A2A card: its name, version, and advertised skills."""
    return await _session.card()


@mcp.tool()
async def send_raw(text: str, context_id: str | None = None, task_id: str | None = None) -> str:
    """Escape hatch: send an arbitrary text message to the agent; return its reply + ids + state.

    Prefer gather_knowledge / refine; use this only for something they do not cover.
    """
    res = await _session.ask(text, context_id=context_id, task_id=task_id)
    return (
        f"[state: {res.state or 'message'}] [context_id: {res.context_id}] "
        f"[task_id: {res.task_id}]\n{res.text}"
    )


@mcp.prompt()
def test(jira_key: str = "", depth: str = "2") -> str:
    """Run the full Testing-Agent pipeline for a Jira ticket (gather -> ... -> implement)."""
    return test_prompt(jira_key, depth)


def http_app():
    """Streamable-HTTP ASGI app, gated by KGA_BRIDGE_BEARER_TOKEN when set (see common.bridge)."""
    return build_http_app(mcp, "KGA_BRIDGE")
