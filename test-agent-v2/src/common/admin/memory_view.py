"""F2 — memory introspection: view the four tiers (working / episodic / semantic / procedural)."""

from __future__ import annotations

import asyncio

from common import learn
from common.admin._shared import (
    _RUNS_PREFIX,
    _first_table_count,
    _kinds_str,
    _run_contexts,
    _store,
)


async def view_memory(bank, engine, tier: str = "all", context_id: str | None = None) -> str:
    """View the four memory tiers (F2): working / episodic / semantic / procedural.

    `engine` is the shared async SQLAlchemy engine (or None). DB-backed rows degrade gracefully when
    no DB is configured. `tier="all"` runs every section (skipping working without a context_id)."""
    tier = (tier or "all").lower()
    sections: list[str] = []
    if tier in ("all", "working"):
        sections.append(await asyncio.to_thread(_view_working, bank, context_id))
    if tier in ("all", "episodic"):
        sections.append(await _view_episodic(bank, engine, context_id))
    if tier in ("all", "semantic"):
        sections.append(await _view_semantic(bank, engine))
    if tier in ("all", "procedural"):
        sections.append(_view_procedural())
    if not sections:
        return f"Unknown tier {tier!r}. Use: all | working | episodic | semantic | procedural."
    return "\n\n".join(sections)


def _view_working(bank, context_id: str | None) -> str:
    """Working (in-context) memory = the per-context refine working set (ADK session state lives in the
    DB session table, surfaced via the semantic/episodic DB counts)."""
    if not context_id:
        runs = _run_contexts(bank)
        return ("## Working (in-context)\nProvide a context_id. Known runs: "
                + (", ".join(runs) if runs else "none") + ".")
    state = bank.read_refine_state(context_id)
    qs = bank.read_questions(context_id)
    answers = bank.read_answers(context_id)
    understanding = bank.read_understanding(context_id)
    return (f"## Working (in-context) — {context_id}\n"
            f"- refine state: {'done' if state.get('done') else ('active pass ' + str(state.get('pass', '?'))) if state else 'none'}\n"
            f"- pending rounds: {', '.join(state.get('pending', [])) or '-'}\n"
            f"- questions: {len(qs)}  answers: {len(answers)}\n"
            f"- understanding brief: {'present' if understanding else 'none'}")


async def _view_episodic(bank, engine, context_id: str | None) -> str:
    """Episodic = what happened: recent run logs + captured lessons + A2A task rows."""
    logs, lessons = await asyncio.to_thread(_episodic_bank_reads, bank)  # blocking GCS off the loop
    lines = ["## Episodic (history)", f"- run logs: {len(logs)}"]
    lines += [f"    - {name}" for name in logs[:10]]
    lines.append(f"- lessons captured: {len(lessons)}")
    if engine is None:
        lines.append("- A2A tasks: (in-memory, no DB configured)")
    else:
        count = await _first_table_count(engine, ("tasks", "task"))
        lines.append(f"- A2A task rows: {count if count is not None else 'n/a (no task table)'}")
    return "\n".join(lines)


def _episodic_bank_reads(bank) -> tuple[list[str], list]:
    """The blocking GCS reads for the episodic tier — run in a thread (run logs + lessons)."""
    logs = sorted((b.name[len(_RUNS_PREFIX):] for b in _store(bank).iter_blobs(_RUNS_PREFIX)), reverse=True)
    return logs, learn.search_lessons(bank)


async def _view_semantic(bank, engine) -> str:
    """Semantic = generalised facts: the GCS index + the pgvector projection, with a drift signal."""
    graph, _ = await asyncio.to_thread(bank.load_index)  # blocking GCS off the loop
    by_type: dict[str, int] = {}
    for n in graph.nodes.values():
        by_type[n.get("type", "?")] = by_type.get(n.get("type", "?"), 0) + 1
    lines = ["## Semantic (facts)",
             f"- index nodes: {len(graph.nodes)} ({_kinds_str(by_type)})",
             f"- index edges: {len(graph.edges)}"]
    if engine is None:
        lines.append("- pgvector: (no DB configured — GCS index is the sole tier)")
        return "\n".join(lines)
    node_rows = await _first_table_count(engine, ("memory_node",))
    edge_rows = await _first_table_count(engine, ("memory_edge",))
    lines.append(f"- pgvector memory_node rows: {node_rows if node_rows is not None else 'n/a'}")
    lines.append(f"- pgvector memory_edge rows: {edge_rows if edge_rows is not None else 'n/a'}")
    if node_rows is not None and node_rows != len(graph.nodes):
        lines.append(f"- ⚠ drift: index has {len(graph.nodes)} nodes but pgvector has {node_rows} "
                     f"(rebuild via pg/backfill.py)")
    return "\n".join(lines)


# ponytail: static mirror of the pipeline tool surfaces — common must not import the agent packages
# (that would be a common→agent back-dependency). Kept short; update if a bridge's tool set changes.
_PROCEDURAL_AGENTS = (
    ("knowledge_gathering", "crawl + distill + interrogate a ticket into the pack",
     ("gather_knowledge", "gather_codebase", "refine", "get_questions", "get_understanding",
      "search_memory", "get_note", "search_lessons", "veto_lesson", "approve")),
    ("test_plan_definition", "define + implement the test plan from the pack",
     ("define_plan", "get_plan", "approve_plan", "implement_plan", "get_scenarios", "get_coverage")),
    ("test_evaluation", "score the pack / plan (read-only quality gate)",
     ("evaluate_pack", "evaluate_plan")),
    ("admin_agent", "[ADMIN — non-pipeline] memory & history operator utility",
     ("list_runs", "get_run", "view_memory", "backup_memory", "list_backups", "wipe_all")),
)


def _view_procedural() -> str:
    """Procedural = how the agents operate: agents + tool names + interrogation rounds. Static, no DB."""
    lines = ["## Procedural (rules / skills)"]
    for name, role, toolnames in _PROCEDURAL_AGENTS:
        lines.append(f"- **{name}** — {role}")
        lines.append(f"    tools: {', '.join(toolnames)}")
    lines.append(f"- interrogation rounds: {', '.join(_interrogation_rounds())}")
    lines.append("- assured-loop rubric: generate→judge→gate→reflect→regenerate (TPD_ASSURED)")
    return "\n".join(lines)


def _interrogation_rounds() -> list[str]:
    import pkgutil

    from common.interrogate import round as round_pkg

    return sorted(m.name for m in pkgutil.iter_modules(round_pkg.__path__) if m.name != "base")
