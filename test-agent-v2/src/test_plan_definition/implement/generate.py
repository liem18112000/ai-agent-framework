"""Test Plan implement (Stage B) — one-shot artifact generation from a confirmed plan."""

from __future__ import annotations

from common.testplan import memory as store
from common.testplan.models import (
    CONFIRMED,
    TEST_PLAN,
    TEST_SCENARIO,
    ImplementResult,
    TestPlan,
    TestPlanRun,
    TestScenario,
)
from common.testplan.pack import load_plan_pack
from test_plan_definition.implement.assured import assured_enabled, run_assured_scenarios
from test_plan_definition.implement.gherkin import export_features
from test_plan_definition.implement.scenarios import generate_scenarios
from test_plan_definition.implement.steps import generate_all_steps
from test_plan_definition.implement.testdata import generate_test_data
from test_plan_definition.monitoring import get_logger

log = get_logger("implement.generate")


async def implement_plan(bank, context_id: str, *, run_id: str = "implement", now: str = "",
                         detail: bool = False, assured: bool = False,
                         model=None) -> ImplementResult:
    plan = store.read_plan(bank, context_id)
    if plan is None:
        return ImplementResult(message=f"No test plan for {context_id}; run define first.")
    if plan.status != CONFIRMED:
        return ImplementResult(plan=plan, message=f"Test plan for {context_id} is {plan.status}; "
                              "approve it (resolve open gaps) before implementing.")

    plan_pack = load_plan_pack(bank, context_id)
    # I3: only `scenarios` runs an LLM on the default path; test-data/steps stay behind `detail`.
    test_data = await generate_test_data(plan, plan_pack, now=now, detail=detail, model=model)
    # P4 (§3.4): the opt-in assured loop replaces the single blind scenario call with a bounded
    # generate→judge→gate→reflect→regenerate loop. Default OFF keeps the I3 single-call path.
    quality = None
    if assured_enabled(assured):
        scenarios, quality = await run_assured_scenarios(bank, context_id, plan, plan_pack,
                                                         test_data, now=now, model=model)
    else:
        scenarios = await generate_scenarios(plan, plan_pack, test_data, now=now, model=model)
    steps = await generate_all_steps(scenarios, plan, plan_pack, test_data, now=now,
                                     detail=detail, model=model)

    store.write_test_data(bank, context_id, test_data)
    store.write_scenarios(bank, context_id, scenarios, steps)
    store.write_steps(bank, context_id, steps)
    feature = export_features(bank, context_id) or ""
    bank.update_index(lambda g: _add_provenance(g, plan, scenarios))
    _project_nodes(bank, plan, scenarios)

    run = TestPlanRun(
        run_id=run_id, context_id=context_id, plan_id=plan.id,
        scenarios_written=len(scenarios), steps_written=len(steps),
        testdata_written=len(test_data), confidence=plan.confidence, started=now, ended=now,
    )
    store.append_plan_run_log(bank, run)
    log.info("implement done: %d scenarios, %d steps, %d test-data, feature=%s, quality=%s",
             len(scenarios), len(steps), len(test_data), bool(feature),
             quality.final_score if quality else "n/a")
    return ImplementResult(plan, test_data, scenarios, steps, feature, run, quality=quality)


def _project_nodes(bank, plan: TestPlan, scenarios: list[TestScenario]) -> None:
    """Enqueue plan + scenario index nodes for the pgvector projector (best-effort)."""
    try:
        from common.memory.pg.project import index_on_write

        index_on_write(bank, plan.id, TEST_PLAN)
        for sc in scenarios:
            index_on_write(bank, sc.id, TEST_SCENARIO)
    except Exception as exc:  # noqa: BLE001 — projection is best-effort
        log.warning("implement: index-node projection skipped (%s)", exc)


def _add_provenance(graph, plan: TestPlan, scenarios: list[TestScenario]) -> None:
    """Add plan + scenario nodes and their edges to the shared index (scenario -> insight/note)."""
    graph.nodes[plan.id] = {"id": plan.id, "type": TEST_PLAN, "title": f"Test Plan {plan.context_id}"}
    for ref in plan.source_refs:
        graph.edges[f"{plan.id}->{ref}"] = {
            "source_id": plan.id, "target": ref, "type": TEST_PLAN, "origin": "plan", "in_scope": True}
    for sc in scenarios:
        graph.nodes[sc.id] = {"id": sc.id, "type": TEST_SCENARIO, "title": sc.title}
        for ref in sc.source_refs:
            graph.edges[f"{sc.id}->{ref}"] = {
                "source_id": sc.id, "target": ref, "type": TEST_SCENARIO,
                "origin": sc.kind, "in_scope": True}
