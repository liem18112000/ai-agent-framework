"""Read-only memory/lesson tools — plain typed functions, the canonical ADK tool form."""

from __future__ import annotations

from common import learn
from common.memory import retrieve
from common.memory.factory import build_bank


async def search_memory(query: str = "") -> str:
    """Search the knowledge index (link graph) in the memory bank."""
    nodes = await retrieve.search_nodes(build_bank(), query)
    if not nodes:
        return "No matching nodes."
    return "\n".join(f"{n.get('id')} [{n.get('type')}] — {n.get('title', '')}" for n in nodes)


async def get_note(note_id: str) -> str:
    """Return one distilled note from the memory bank by id (exact index lookup, backend-independent)."""
    bank = build_bank()
    graph, _ = bank.load_index()  # MEM-01: resolve id->type via the O(1) index, not fuzzy search
    node = graph.nodes.get(note_id)
    node_type = node.get("type") if node else None
    if node_type and (md := bank.read_note_md(note_id, node_type)):
        return md
    return f"No note found for id {note_id!r}."


async def search_lessons(query: str = "") -> str:
    """List the agent's captured self-learning lessons."""
    return learn.search_lessons(build_bank(), query)


async def veto_lesson(insight_id: str) -> str:
    """Retract a wrong lesson so it is excluded from recall and never re-learned."""
    return learn.veto_lesson(build_bank(), insight_id)
