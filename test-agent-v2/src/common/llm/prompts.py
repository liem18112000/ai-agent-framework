"""Prompt + text templates for the Claude-on-Vertex generators."""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.llm import templates
from common.models import Insight, Question

if TYPE_CHECKING:
    from common.interrogate.pack import Pack


GUIDANCE = {
    "business": (
        "ROUND: Business (product-owner judgement) — vinnstack interrogate-business method.\n"
        "Principle: Don't ask what you can answer. Resolve everything derivable from the pack, linked "
        "tickets, and domain knowledge yourself (mark those self-answered with your recommendation as "
        "the answer); surface ONLY the genuine business-judgement calls a product owner must make. "
        "This round also OWNS sequencing/process/timing decisions — ship-now vs wait on a stakeholder, "
        "parallel vs gated rollout, who signs off when; if one matters, ask it here.\n"
        "Pitfalls: don't ask decisions the brief already implies (self-answer + note the assumption); "
        "NO technical/implementation questions; every question must change what gets built or verified."
    ),
    "technical": (
        "ROUND: Technical (architecture-level engineering direction) — vinnstack interrogate-technical.\n"
        "Principle: Ground in the ACTUAL code — use any codegraph note in the pack (real endpoints, "
        "dependency clients, enums, god-node modules) — but ask at SOLUTION ALTITUDE. Resolve anything "
        "answerable from the code and the committed business answers (self-answer + cite). What remains "
        "must be a genuine engineering DIRECTION choice a tech lead can answer in a refinement meeting "
        "without opening the code.\n"
        "Altitude rule (core constraint): RIGHT altitude decides HOW the problem is solved at the "
        "module/service level — which approach/pattern; which module owns a responsibility and the "
        "contract between modules (who calls whom, who stores what); build-new vs reuse vs buy. "
        "TOO DETAILED (do NOT ask — pick a sensible default and state it inside the recommended option "
        "as an assumption): payload/field names, timing mechanics, config formats, class/method design, "
        "step-by-step call order, migration mechanics, project sequencing. Litmus: if a tech lead can't "
        "answer it in ~2 min without reading code, raise the altitude or resolve it as an assumption.\n"
        "Pitfalls: don't ask what the code already answers; don't contradict the business round — build "
        "on it; no sequencing/timing (that's business); options must be genuinely different solution "
        "shapes, not the proposal vs strawmen."
    ),
    "qa": (
        "ROUND: QA/QC (test-design, pre-BDD) — vinnstack interrogate-qa. Quality is the first priority: "
        "a smaller set that verifies the real system beats a large set that 'looks done'.\n"
        "Principle: Don't ask what the stories/flows/code already answer (resolve + cite). Surface ONLY "
        "genuine QA/QC judgement calls — where two valid test strategies exist and the choice changes "
        "WHAT gets verified, HOW reliably, or in WHAT ORDER.\n"
        "Look for questions in: ambiguous/conflicting acceptance criteria (flag, don't guess a reading); "
        "CROSS-story risks a single-story pass misses (shared setup/Background reuse, data/sequencing "
        "dependencies between stories, inconsistent coverage conventions); executability needs (test "
        "data/fixtures, target environment, tenant/account setup, which external services to stub vs hit "
        "for real); non-functional/risk concerns the AC omits but the code enforces (authz/security "
        "classes, concurrency, performance thresholds) as boundary/error scenarios; and a RISK pass — "
        "which areas (payment, auth, data-loss, compliance) need more than the happy/negative/boundary/"
        "error floor vs which are low-risk.\n"
        "Pitfalls: don't ask what's already answered; don't let 'more scenarios' stand in for quality; "
        "don't invent data/environment needs — ask only when the material genuinely doesn't say."
    ),
}


def _render(key: str, params: dict) -> str:
    """Render an engine-path prompt from the store (falls back to the image bodies without a DB)."""
    from common.llm.templates import DEFAULTS
    from common.prompts import store_for

    return store_for(DEFAULTS).get(key).render(params)


def question_prompt(pack: Pack, round_name: str, *, include_context: bool = True) -> str:
    """Claude-on-Vertex prompt asking for one interrogation round's questions.

    `include_context=False` drops the trailing pack dump so the caller can pass `pack.summary_text()`
    as a stable `cache_prefix` (Anthropic prompt caching) — the pack is then reused across the round's
    LLM calls instead of re-sent uncached each round (mirrors the define path)."""
    return _render(templates.QUESTIONS, {
        "guidance": GUIDANCE.get(round_name, f"ROUND: {round_name}"),
        "round_prefix": round_name[:3],
        "ctx": f"\n\nContext pack:\n{pack.summary_text()}" if include_context else "",
    })


def understanding_prompt(
    pack: Pack, insights: list[Insight], open_questions: list[Question], confidence: str,
    deferred: list[Question] | None = None,
) -> str:
    """Claude-on-Vertex prompt to restate the agent's understanding for a human to confirm."""
    # The 'Out/deferred' heading needs the deferred questions behind it — the heuristic sibling renders
    # them, so the LLM brief must too, else it silently hides gaps the agent chose not to resolve.
    return _render(templates.UNDERSTANDING, {
        "confidence": confidence,
        "pack": pack.summary_text(),
        "decided": "\n".join(f"- {i.statement} ({i.answered_by})" for i in insights) or "(none)",
        "deferred": "\n".join(f"- {q.question}" for q in (deferred or [])) or "(none)",
        "opens": "\n".join(f"- {q.question}" for q in open_questions) or "(none)",
    })
