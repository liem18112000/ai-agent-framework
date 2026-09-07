"""Generate test scenarios from a confirmed plan (heuristic; POC).

One happy-path scenario per grounded note (the acceptance-criterion proxies in the pack),
plus a negative scenario when the plan's metrics call for negative coverage. Each scenario
carries source_refs back to the note it covers, for cross-stage provenance.
"""

from __future__ import annotations

from common.llm.vertex import vertex_config
from common.memory.bank import _slug
from test_plan_definition.models import (
    BOUNDARY,
    ERROR,
    HAPPY,
    NEGATIVE,
    TestData,
    TestPlan,
    TestScenario,
)
from test_plan_definition.pack import PlanPack

_MAX_NOTES = 8  # cap the note fan-out — enough to cover a full story batch (× the coverage matrix)

# The coverage bar the agent applies per behaviour — mirrors story-to-bdd-scenarios
# (happy + negative + boundary + error). A plan whose metrics say "happy only" opts back down.
_FULL_COVERAGE = (HAPPY, NEGATIVE, BOUNDARY, ERROR)
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
    """Which scenario kinds to generate per behaviour: the full matrix unless the plan's
    metrics explicitly ask for happy-only coverage."""
    metrics = " ".join(plan.metrics).lower()
    if "happy only" in metrics or "happy-only" in metrics:
        return (HAPPY,)
    return _FULL_COVERAGE


def generate_scenarios(
    plan: TestPlan, plan_pack: PlanPack, test_data: list[TestData], *, now: str = ""
) -> list[TestScenario]:
    """Claude-on-Vertex scenarios when VERTEX_* is configured (heuristic on miss), else heuristic."""
    cfg = vertex_config()
    if cfg:
        proj, loc, model = cfg
        from test_plan_definition.llm.scenarios import claude_scenarios

        scs = claude_scenarios(plan, plan_pack, test_data,
                               project=proj, location=loc, model=model, now=now)
        if scs:  # non-empty on success; None/[] falls through to the heuristic
            return scs
    return heuristic_scenarios(plan, plan_pack, test_data, now=now)


def heuristic_scenarios(
    plan: TestPlan, plan_pack: PlanPack, test_data: list[TestData], *, now: str = ""
) -> list[TestScenario]:
    ctx = plan.context_id
    method = plan.methodology[0] if plan.methodology else "api"
    data_refs = [d.id for d in test_data]
    kinds = _coverage_kinds(plan)

    targets = [(n.id, n.title) for n in plan_pack.pack.grounded[:_MAX_NOTES]]
    if not targets:  # fall back to the plan's scope when the pack has no grounded notes
        targets = [(s, s) for s in plan.scope[:_MAX_NOTES]]

    out: list[TestScenario] = []
    for ref, title in targets:
        base = _slug(ref)
        for kind in kinds:  # full coverage matrix per behaviour (happy + negative + boundary + error)
            out.append(TestScenario(
                id=f"scenario:{ctx}:{base}:{kind}", plan_id=plan.id,
                title=f"{title} — {_KIND_SUFFIX[kind]}",
                kind=kind, methodology=method,
                description=f"Exercise the {kind} case for '{title}' via {method}.",
                rationale=_KIND_RATIONALE[kind],
                data_refs=data_refs, source_refs=[ref], created_at=now))
    return out
