"""Human Markdown rendering for notes, the index, run-logs, and refinement insights."""

from __future__ import annotations

import json

from common.memory import template as tmpl
from common.models import Graph, Insight, Note, RefinementRun, RunLog


def _section(heading: str, items: list) -> str:
    """A markdown `- item` bullet section (blank line + heading), or '' when there are none."""
    if not items:
        return ""
    body = "\n".join(f"- {i}" for i in items)
    return f"\n{heading}\n\n{body}\n"


def render_note_md(note: Note) -> str:
    link_rows = "\n".join(f"| {lr.url} | {lr.type} | {lr.origin} | {'yes' if lr.in_scope else 'no'} |" for lr in note.links)
    md = tmpl.NOTE_MD.format(id=note.id, type=note.type, source_url=note.source_url, title=note.title,
                             fetched_at=note.fetched_at, depth=note.depth, run_id=note.run_id,
                             confidence=note.confidence, links_out=len(note.links),
                             heading=note.title or note.id, synopsis=note.synopsis, link_rows=link_rows)
    return md + _section("## Backlinks", note.backlinks)


def render_index_md(graph: Graph) -> str:
    rows = "\n".join(f"| {n['id']} | {n['type']} | {n.get('title', '')} |" for n in graph.nodes.values())
    return tmpl.INDEX_MD.format(summary=f"{len(graph.nodes)} nodes · {len(graph.edges)} edges", rows=rows)


def render_run_log_md(run: RunLog) -> str:
    md = tmpl.RUN_LOG_MD.format(run_id=run.run_id, seed=run.seed, params=json.dumps(run.params, ensure_ascii=False),
                                nodes_fetched=run.nodes_fetched, links_found=run.links_found,
                                confidence=run.confidence, started=run.started, ended=run.ended,
                                sources="\n".join(f"- {s}" for s in run.sources))
    return md + _section("## Gaps (flagged, not dropped)", run.gaps)


def render_insight_md(ins: Insight) -> str:
    md = tmpl.INSIGHT_MD.format(id=ins.id, kind=ins.kind, context_id=ins.context_id, question_id=ins.question_id,
                                answered_by=ins.answered_by, confidence=ins.confidence,
                                source_refs=", ".join(ins.source_refs), created_at=ins.created_at,
                                run_id=ins.run_id, statement=ins.statement)
    if ins.rationale:
        md += f"\n{ins.rationale}\n"
    md += _section("## Rejected options", ins.rejected)
    md += _section("## Builds on", ins.source_refs)
    return md


def render_refine_run_log_md(run: RefinementRun) -> str:
    md = tmpl.REFINE_RUN_LOG_MD.format(run_id=run.run_id, context_id=run.context_id, seed=run.seed,
                                       rounds=", ".join(run.rounds), questions_raised=run.questions_raised,
                                       questions_answered=run.questions_answered, insights_written=run.insights_written,
                                       understanding_confidence=run.understanding_confidence,
                                       started=run.started, ended=run.ended)
    md += _section("## New seeds (re-gathered)", run.new_seeds)
    md += _section("## Open questions left (declared gaps)", run.gaps)
    return md
