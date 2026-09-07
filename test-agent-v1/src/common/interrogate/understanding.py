"""Restate the agent's current understanding as a plain-language brief for a human
to confirm or correct ("Ask AI to clarify its understanding").

Confidence is computed deterministically in code (open questions → low; unconfirmed
agent assumptions → medium; all settled by a human → high). Rendering is Claude-on-Vertex
prose when configured (see `common.llm.understanding`), else a heuristic assembly.
"""

from __future__ import annotations

from collections.abc import Callable

from common.interrogate.pack import Pack
from common.llm.understanding import claude_understanding
from common.llm.vertex import vertex_config
from common.models import ASSUMPTION, DECISION, GAP_SEED, Insight, Question

# (pack, insights, open_questions, deferred, confidence) -> markdown brief
Understander = Callable[[Pack, list[Insight], list[Question], list[Question], str], str]


def restate(
    pack: Pack,
    insights: list[Insight],
    *,
    open_questions: list[Question] | None = None,
    deferred: list[Question] | None = None,
    understander: Understander | None = None,
) -> tuple[str, str]:
    open_questions = list(open_questions or [])
    deferred = list(deferred or [])
    confidence = _confidence(insights, open_questions)
    understander = understander or make_understander()
    md = understander(pack, insights, open_questions, deferred, confidence)
    return md, confidence


def _confidence(insights: list[Insight], open_questions: list[Question]) -> str:
    if open_questions:
        return "low"
    if any(i.confidence == "low" for i in insights):
        return "medium"
    return "high"


def make_understander() -> Understander:
    cfg = vertex_config()
    if cfg:
        proj, loc, model = cfg

        def understander(pack, insights, opens, deferred, confidence):
            return claude_understanding(
                pack, insights, opens, deferred, confidence,
                project=proj, location=loc, model=model,
            )

        return understander
    return heuristic_understanding


def heuristic_understanding(
    pack: Pack,
    insights: list[Insight],
    open_questions: list[Question],
    deferred: list[Question],
    confidence: str,
) -> str:
    who = pack.seed or pack.context_id
    primary = pack.grounded[0] if pack.grounded else None
    decisions = [i for i in insights if i.kind in (DECISION, GAP_SEED)]
    assumptions = [i for i in insights if i.kind == ASSUMPTION]

    lines = [f"## Understanding — {who} (confidence: {confidence})", ""]
    if primary:
        lines += [f"**Problem:** {primary.synopsis or primary.title}", ""]
    lines.append("**Settled decisions:**")
    lines += [f"- {i.statement}" for i in decisions] or ["- (none yet)"]
    lines.append("")
    if assumptions:
        lines.append("**Assumptions (agent defaults — veto if wrong):**")
        lines += [f"- {i.statement}" for i in assumptions]
        lines.append("")
    lines.append("**Open gaps:**")
    lines += [f"- {q.question}" for q in open_questions] or ["- none above the confidence bar"]
    if deferred:
        lines += ["", "**Deferred:**", *[f"- {q.question}" for q in deferred]]
    return "\n".join(lines) + "\n"
