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
)
from common.testplan.pack import PlanPack

# Q2: the four defaults are only a SEED — the kind taxonomy is open. `plan.test_kinds` (elicited in the
# implement `case-design` round) overrides it, so user-added kinds (security, performance, concurrency, …)
# flow straight through. There is NO cap on kinds, and NO cap on notes/cases (§ report Q2).
_DEFAULT_KINDS = (HAPPY, NEGATIVE, BOUNDARY, ERROR)
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
    """The kinds to cover: the plan's elicited `test_kinds` if any (open taxonomy), else the four
    defaults — or just happy when the metrics call for happy-only. Never a closed set."""
    if plan.test_kinds:
        return tuple(plan.test_kinds)
    metrics = " ".join(plan.metrics).lower()
    return (HAPPY,) if "happy only" in metrics or "happy-only" in metrics else _DEFAULT_KINDS


async def generate_scenarios(
    plan: TestPlan, plan_pack: PlanPack, test_data: list[TestData], *, now: str = "", model=None,
) -> list[TestScenario]:
    """The ScenarioGen ``LlmAgent`` (the one default implement LLM call, I3) with a heuristic
    fallback — used whenever no model is configured or the model output is invalid."""
    from test_plan_definition.implement.generate.llm import claude_scenarios

    scs = await claude_scenarios(plan, plan_pack, test_data, now=now, model=model)
    return scs or heuristic_scenarios(plan, plan_pack, test_data, now=now)


def heuristic_scenarios(
    plan: TestPlan, plan_pack: PlanPack, test_data: list[TestData], *, now: str = ""
) -> list[TestScenario]:
    ctx = plan.context_id
    method = plan.methodology[0] if plan.methodology else "api"
    data_refs = [d.id for d in test_data]
    kinds = _coverage_kinds(plan)

    # Q2: no cap — enumerate EVERY grounded note (fall back to scope only when the pack is empty).
    targets = ([(n.id, n.title) for n in plan_pack.pack.grounded]
              or [(s, s) for s in plan.scope])

    return [
        TestScenario(
            id=f"scenario:{ctx}:{_slug(ref)}:{_slug(kind)}", plan_id=plan.id,
            title=f"{title} — {_KIND_SUFFIX.get(kind, kind + ' case')}", kind=kind, methodology=method,
            description=f"Exercise the {kind} case for '{title}' via {method}.",
            rationale=_KIND_RATIONALE.get(kind, f"exercises the {kind} aspect of '{title}'"),
            data_refs=data_refs, source_refs=[ref], created_at=now)
        for ref, title in targets for kind in kinds
    ]
