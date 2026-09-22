"""Restate the agent's current understanding as a plain-language brief for a human"""

from __future__ import annotations

from collections.abc import Callable

from common.interrogate.pack import Pack
from common.llm.understanding import claude_understanding
from common.models import ASSUMPTION, DECISION, GAP_SEED, Insight, Question

Understander = Callable[[Pack, list[Insight], list[Question], list[Question], str], str]


def restate(
    pack: Pack, insights: list[Insight], *, open_questions: list[Question] | None = None,
    deferred: list[Question] | None = None, understander: Understander | None = None,
) -> tuple[str, str]:
    open_questions = list(open_questions or [])
    deferred = list(deferred or [])
    confidence = _confidence(insights, open_questions)
    understander = understander or make_understander()
    return understander(pack, insights, open_questions, deferred, confidence), confidence


def _confidence(insights: list[Insight], open_questions: list[Question]) -> str:
    return "low" if open_questions else "medium" if any(i.confidence == "low" for i in insights) else "high"


def make_understander() -> Understander:
    # Lazy import — see common.interrogate.questions.make_generator for the cycle rationale.
    from common.adk.model import model_configured

    if model_configured():

        def understander(pack, insights, opens, deferred, confidence):
            return claude_understanding(pack, insights, opens, deferred, confidence)

        return understander
    return heuristic_understanding


def heuristic_understanding(
    pack: Pack, insights: list[Insight], open_questions: list[Question], deferred: list[Question], confidence: str,
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
