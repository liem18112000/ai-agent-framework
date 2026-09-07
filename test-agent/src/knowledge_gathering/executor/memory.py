"""Memory-bank read handlers — the `search-memory` and `get-note` skills.

Read-only over the GCS knowledge index + distilled notes (no crawl/LLM/Atlassian).
`search-memory <query>` filters index nodes; `get-note <id>` returns a node's rendered note.
"""

from __future__ import annotations

from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue

from common.learn import search_lessons, veto_lesson
from knowledge_gathering.executor.common import reply
from knowledge_gathering.explore.index import match_index_nodes


def _arg(text: str, cmd: str) -> str:
    """The text after the command word, e.g. `search-memory login` -> `login`."""
    return text.strip()[len(cmd):].strip()


async def run_search_lessons(ex, context: RequestContext, event_queue: EventQueue, bank, text: str) -> None:
    """L5: list captured self-learning lessons (active), optionally filtered by a query."""
    q = _arg(text, "search-lessons")
    rows = search_lessons(bank, q)
    if not rows:
        return await reply(context, event_queue,
                           f"No lessons match '{q}'." if q else "No lessons captured yet.")
    lines = [f"{len(rows)} lesson(s)" + (f" matching '{q}'" if q else "") + ":", ""]
    lines += [f"- [{r['kind']}] {r['statement']}  ({r['id']}, conf={r['confidence']})" for r in rows]
    await reply(context, event_queue, "\n".join(lines))


async def run_veto_lesson(ex, context: RequestContext, event_queue: EventQueue, bank, text: str) -> None:
    """L5: veto a wrong lesson → excluded from recall, never re-learned."""
    lid = _arg(text, "veto-lesson")
    if not lid:
        return await reply(context, event_queue, "Provide a lesson id (from search-lessons).")
    ok = veto_lesson(bank, lid)
    await reply(context, event_queue, f"Vetoed {lid}." if ok else f"No lesson '{lid}' found.")


async def run_search_memory(ex, context: RequestContext, event_queue: EventQueue, bank, text: str) -> None:
    """Search the knowledge index (link graph): list nodes whose id / title / type match the query."""
    q = _arg(text, "search-memory").lower()
    graph, _ = bank.load_index()
    nodes = match_index_nodes(graph, q)
    if not nodes:
        return await reply(
            context, event_queue,
            f"No memory nodes match '{q}'." if q else "The memory index is empty — gather something first.",
        )
    header = (
        f"{len(nodes)} node(s) matching '{q}'" if q
        else f"{len(nodes)} node(s), {len(graph.edges)} edge(s) in the index"
    )
    lines = [header + ":", ""]
    for n in sorted(nodes, key=lambda n: n.get("id", "")):
        title = n.get("title") or ""
        lines.append(f"- {n['id']} [{n.get('type', '?')}]" + (f" — {title}" if title else ""))
    lines += ["", "Fetch one with:  get-note <id>"]
    await reply(context, event_queue, "\n".join(lines))


async def run_get_note(ex, context: RequestContext, event_queue: EventQueue, bank, text: str) -> None:
    """Return a single distilled note by id — the node's type is resolved from the index."""
    note_id = _arg(text, "get-note")
    if not note_id:
        return await reply(
            context, event_queue,
            "Provide a note id, e.g. `get-note jira:LUZ-158390` (ids come from search-memory).",
        )
    graph, _ = bank.load_index()
    node = graph.nodes.get(note_id)
    if node is None:
        return await reply(
            context, event_queue,
            f"No note '{note_id}' in the memory index. Use search-memory to list available ids.",
        )
    note_type = node.get("type", "")
    if md := bank.read_note_md(note_id, note_type):
        return await reply(context, event_queue, md)
    # Sidecar rendered inline if the md blob is missing but the json note exists.
    note = bank.read_note(note_id, note_type)
    if note is None:
        return await reply(context, event_queue, f"Note '{note_id}' is indexed but its content is missing.")
    lines = [
        f"# {note.title or note.id}  [{note.type}]",
        f"id: {note.id}",
        f"source: {note.source_url}",
        f"confidence: {note.confidence}",
        "",
        note.synopsis or "(no synopsis)",
        "",
        f"links: {len(note.links)} · backlinks: {len(note.backlinks)}",
    ]
    await reply(context, event_queue, "\n".join(lines))
