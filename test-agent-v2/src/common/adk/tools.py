"""Read-only memory/lesson tools — plain typed functions, the canonical ADK tool form.

Per the adk-samples idiom (E3), these are bare `async def` functions with type hints + Google-style
docstrings; ADK builds the tool schema from the signature and auto-wraps them when passed in an
agent's `tools=[...]`. No `FunctionTool(...)` wrapper. The heavy work (retrieval, lesson governance)
lives in the framework-neutral engine and is already tested; each builds its own bank per call.
Gather/crawl is NOT here — it is a custom BaseAgent (A1), not an LLM tool.
"""

from __future__ import annotations

from common import learn
from common.memory import retrieve
from common.memory.factory import build_bank


async def search_memory(query: str = "") -> str:
    """Search the knowledge index (link graph) in the memory bank.

    Args:
        query: id / title / type substring to filter by; empty lists everything.

    Returns:
        One `id [type] — title` row per matching node, or a "no matches" message.
    """
    nodes = await retrieve.search_nodes(build_bank(), query)
    if not nodes:
        return "No matching nodes."
    return "\n".join(f"{n.get('id')} [{n.get('type')}] — {n.get('title', '')}" for n in nodes)


async def get_note(note_id: str) -> str:
    """Return one distilled note from the memory bank by id.

    Args:
        note_id: the node id from search_memory, e.g. "jira:LUZ-158390".

    Returns:
        The note's rendered markdown, or a "not found" message.
    """
    bank = build_bank()
    nodes = await retrieve.search_nodes(bank, note_id)
    match = next((n for n in nodes if n.get("id") == note_id), None)
    node_type = (match or {}).get("type")
    if node_type and (md := bank.read_note_md(note_id, node_type)):
        return md
    return f"No note found for id {note_id!r}."


async def search_lessons(query: str = "") -> str:
    """List the agent's captured self-learning lessons.

    Args:
        query: statement substring to filter by; empty lists all lessons.

    Returns:
        The matching lessons, one per row (id + statement).
    """
    return learn.search_lessons(build_bank(), query)


async def veto_lesson(insight_id: str) -> str:
    """Retract a wrong lesson so it is excluded from recall and never re-learned.

    Args:
        insight_id: the lesson id from search_lessons.

    Returns:
        A confirmation message.
    """
    return learn.veto_lesson(build_bank(), insight_id)


def memory_tools() -> list:
    """The read-only tools shared by both agents — bare functions (ADK auto-wraps in `tools=[...]`)."""
    return [search_memory, get_note, search_lessons, veto_lesson]
