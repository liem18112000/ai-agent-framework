"""Generate test scenarios from a confirmed plan (heuristic; POC)."""

from __future__ import annotations

from common.memory.bank import _slug
from common.testplan.models import (
    BOUNDARY,
    ERROR,
    HAPPY,
    NEGATIVE,
    TestData,
    TestPlan,
    TestScenario,
    effective_kinds,
)
from common.testplan.pack import PlanPack

# Q2: the four defaults are only a SEED — the kind taxonomy is open and ADDITIVE. `effective_kinds`
# unions the elicited `plan.test_kinds` (case-design round) on top of the four, so user-added kinds
# (security, performance, concurrency, …) flow through WITHOUT ever dropping the base four. No cap on
# kinds, no cap on notes/cases (§ report Q2).
_KIND_SUFFIX = {
    HAPPY: "happy path",
    NEGATIVE: "negative — invalid/unauthorized input is rejected",
    BOUNDARY: "boundary — empty / single / maximum limits",
    ERROR: "error handling — dependency/failure path",
}
_KIND_RATIONALE = {
    HAPPY: "confirms the primary success path works end to end",
    NEGATIVE: "confirms invalid or unauthorized input is safely rejected with no side effects",
    BOUNDARY: "confirms correct behaviour at the input limits (empty / single / maximum)",
    ERROR: "confirms graceful failure and a consistent end state when a dependency fails",
}


def _coverage_kinds(plan: TestPlan) -> tuple[str, ...]:
    """The kinds to cover: the base four ∪ the plan's elicited extras (additive, never a closed set),
    or just happy when the metrics call for happy-only. See ``effective_kinds`` — the single resolver."""
    return tuple(effective_kinds(plan))


async def generate_scenarios(
    plan: TestPlan, plan_pack: PlanPack, test_data: list[TestData], *, now: str = "", model=None,
) -> list[TestScenario]:
    """The ScenarioGen ``LlmAgent`` (the one default implement LLM call, I3) with a heuristic
    fallback — used whenever no model is configured or the model output is invalid."""
    from test_plan_definition.implement.generate.llm import claude_scenarios

    scs = await claude_scenarios(plan, plan_pack, test_data, now=now, model=model)
    return scs or heuristic_scenarios(plan, plan_pack, test_data, now=now)


def heuristic_scenarios(
    plan: TestPlan, plan_pack: PlanPack, test_data: list[TestData], *, now: str = "",
    only_ids: set[str] | None = None,
) -> list[TestScenario]:
    ctx = plan.context_id
    method = plan.methodology[0] if plan.methodology else "api"
    data_refs = [d.id for d in test_data]
    kinds = _coverage_kinds(plan)

    # Q2: no cap — enumerate EVERY grounded note (fall back to scope only when the pack is empty).
    # `only_ids` narrows to one generation batch's units — the per-batch degrade path in the LLM
    # generator, so a single failed batch falls back for its units alone, not the whole suite.
    targets = ([(n.id, n.title) for n in plan_pack.pack.grounded]
              or [(s, s) for s in plan.scope])
    if only_ids is not None:
        targets = [t for t in targets if t[0] in only_ids]

    return [
        TestScenario(
            id=f"scenario:{ctx}:{_slug(ref)}:{_slug(kind)}", plan_id=plan.id,
            title=f"{title} — {_KIND_SUFFIX.get(kind, kind + ' case')}", kind=kind, methodology=method,
            description=f"Exercise the {kind} case for '{title}' via {method}.",
            rationale=_KIND_RATIONALE.get(kind, f"exercises the {kind} aspect of '{title}'"),
            data_refs=data_refs, source_refs=[ref], created_at=now)
        for ref, title in targets for kind in kinds
    ]
