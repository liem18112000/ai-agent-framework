"""Test Plan implement (Stage B) — one-shot artifact generation from a confirmed plan."""

from __future__ import annotations

import asyncio

from common.interrogate.round.case_design import EXTRA_KINDS, kinds_from_answer
from common.testplan import memory as store
from common.testplan.llm.prompts import refresh_store
from common.testplan.models import (
    CONFIRMED,
    TEST_PLAN,
    TEST_SCENARIO,
    ImplementResult,
    TestPlan,
    TestPlanRun,
    TestScenario,
    TestStep,
)
from common.testplan.pack import load_plan_pack
from test_plan_definition.implement.assured import run_assured_scenarios
from test_plan_definition.implement.generate.scenarios import upload_cases
from test_plan_definition.implement.generate.steps import generate_all_steps
from test_plan_definition.implement.generate.testdata import generate_test_data
from test_plan_definition.monitoring import get_logger

log = get_logger("implement.generate")


async def implement_plan(bank, context_id: str, *, run_id: str = "implement", now: str = "",
                         detail: bool = False, model=None, guidance: str = "",
                         max_rounds: int | None = None) -> ImplementResult:
    plan = await asyncio.to_thread(store.read_plan, bank, context_id)  # blocking GCS reads/writes → off the loop
    if plan is None:
        return ImplementResult(message=f"No test plan for {context_id}; run define first.")
    if plan.status != CONFIRMED:
        return ImplementResult(plan=plan, message=f"Test plan for {context_id} is {plan.status}; "
                              "approve it (resolve open gaps) before implementing.")

    # `guidance=` free text is otherwise only an LLM reflection, so extra kinds the user asked for
    # (security/concurrency/i18n…) never reached plan.test_kinds and generation used only the seed
    # defaults. Fold any guidance-named EXTRA kinds into the plan here (union, defaults untouched).
    if guidance and (named := [k for k in kinds_from_answer(guidance) if k in EXTRA_KINDS]):
        plan.test_kinds = list(dict.fromkeys([*(plan.test_kinds or []), *named]))
        await asyncio.to_thread(store.write_plan, bank, plan)

    plan_pack = await asyncio.to_thread(load_plan_pack, bank, context_id)
    # P2/P4 — load + PIN the prompt snapshot once, before any generator renders. Every prompt
    # in this run then reads the same bodies, so a publish landing mid-run cannot make round 3
    # incomparable to round 1; the pins ride onto the run log as provenance.
    prompt_versions = await refresh_store()
    # test-data/steps stay behind `detail` (heuristic by default — one LLM path unless opted in). On a
    # resume (an unfinished assured pass exists) reuse the persisted set so a `detail` LLM test-data call
    # isn't repeated on every step; persist it up front so the next step can read it back.
    saved = await asyncio.to_thread(store.read_assured_state, bank, context_id)
    resuming = bool(saved.get("iterations")) and not saved.get("accepted")
    test_data = (await asyncio.to_thread(store.read_test_data, bank, context_id) if resuming else []) \
        or await generate_test_data(plan, plan_pack, now=now, detail=detail, model=model)
    # A file-upload requirement → a bound multipart scenario + its file fixture (executable, not prose).
    upload_data, upload_scenarios = upload_cases(plan, plan_pack, now=now)
    for f in upload_data:                                   # dedupe by id so a resume/re-run doesn't duplicate
        if not any(d.id == f.id for d in test_data):
            test_data.append(f)
    await asyncio.to_thread(store.write_test_data, bank, context_id, test_data)
    # P4 (§3.4): the assured loop (generate→judge→gate→reflect→regenerate) is ALWAYS the scenario path
    # now — no opt-in. It trades away I3 (adds the judge call per round); TPD_ASSURED_MAX_ITERS bounds it.
    # `max_rounds` chunks it: one MCP call runs that many rounds then returns in-progress (done=False) so
    # a single call stays under the client's tool idle timeout — the fix for implement_plan erroring.
    scenarios, quality, pending = await run_assured_scenarios(
        bank, context_id, plan, plan_pack, test_data, now=now, model=model, guidance=guidance,
        max_rounds=max_rounds)
    for s in upload_scenarios:  # bound upload scenarios are deterministic — appended after the judged loop
        if not any(x.id == s.id for x in scenarios):
            scenarios.append(s)
    if pending:  # loop paused with rounds remaining — persist the partial scenarios, defer the finalize
        await asyncio.to_thread(store.write_scenarios, bank, context_id, scenarios)
        return ImplementResult(plan, test_data, scenarios, quality=quality, done=False,
                               message="Assured loop in progress — re-run implement_plan to continue.")
    steps = await generate_all_steps(scenarios, plan, plan_pack, test_data,
                                     detail=detail, model=model)

    # Finalization is a burst of blocking GCS writes → run each off the event loop (awaited in order).
    await asyncio.to_thread(store.write_scenarios, bank, context_id, scenarios, steps)
    await asyncio.to_thread(store.write_steps, bank, context_id, steps)
    feature = await asyncio.to_thread(export_features, bank, context_id) or ""
    await asyncio.to_thread(bank.update_index, lambda g: _add_provenance(g, plan, scenarios))
    await asyncio.to_thread(_project_nodes, bank, plan, scenarios)
    coverage = await asyncio.to_thread(_build_coverage, bank, context_id, plan, plan_pack, scenarios)
    await asyncio.to_thread(_build_diagrams, bank, context_id, plan)

    run = TestPlanRun(
        run_id=run_id, context_id=context_id, plan_id=plan.id,
        scenarios_written=len(scenarios), steps_written=len(steps),
        testdata_written=len(test_data), confidence=plan.confidence, started=now, ended=now,
        prompt_versions=prompt_versions,
    )
    await asyncio.to_thread(store.append_plan_run_log, bank, run)
    await asyncio.to_thread(store.write_prompt_versions, bank, context_id, prompt_versions)  # P7: attributable scores
    log.info("implement done: %d scenarios, %d steps, %d test-data, feature=%s, quality=%s, %s",
             len(scenarios), len(steps), len(test_data), bool(feature),
             quality.final_score if quality else "n/a", coverage or "no-coverage")
    return ImplementResult(plan, test_data, scenarios, steps, feature, run, quality=quality,
                           coverage_summary=coverage)


def render_feature(subject: str, scenarios: list[TestScenario], steps: list[TestStep]) -> str:
    """Render generated scenarios/steps as a BDD/Gherkin ``.feature`` body."""
    by_scenario: dict[str, list[TestStep]] = {}
    for st in steps:
        by_scenario.setdefault(st.scenario_id, []).append(st)

    lines = [f"Feature: {subject}", ""]
    for sc in scenarios:
        steps_sorted = sorted(by_scenario.get(sc.id, []), key=lambda s: s.order)
        lines += [f"  @{sc.kind} @{sc.methodology}", f"  Scenario: {sc.title}"]
        if sc.data_refs and not any(s.keyword for s in steps_sorted):
            lines.append(f"    Given the test data ({', '.join(sc.data_refs)}) is prepared")
        for st in steps_sorted:
            lines += [f"    {st.keyword} {st.action}"] if st.keyword else \
                     [f"    When {st.action}", f"    Then {st.expected}"]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def export_features(bank, context_id: str) -> str | None:
    """Write memory/test-plan/<ctx>/features/<ctx>.feature from the persisted scenarios/steps."""
    scenarios = store.read_scenarios(bank, context_id)
    if not scenarios:
        return None
    text = render_feature(scenarios[0].title.split(" — ")[0], scenarios, store.read_steps(bank, context_id))
    store.write_feature(bank, context_id, context_id, text)
    return text


def _build_diagrams(bank, context_id: str, plan) -> None:
    """Persist diagram-as-code (mermaid) from the plan + persisted coverage, so the client can render
    and download them. Best-effort — a diagram failure never breaks implement."""
    try:
        from common.testplan.diagrams import build_diagrams
        diagrams = build_diagrams(plan, store.read_coverage(bank, context_id))
        if diagrams:
            store.write_diagrams(bank, context_id, diagrams)
    except Exception as exc:  # noqa: BLE001 — diagrams are a best-effort overlay, never break implement
        log.warning("implement: diagrams skipped (%s)", exc)


def _build_coverage(bank, context_id: str, plan, plan_pack, scenarios) -> str:
    """Q5: build + persist the codegraph coverage matrix; return its one-line summary (best-effort)."""
    try:
        from common.testplan.coverage import (
            build_coverage_matrix,
            coverage_summary,
            render_coverage_md,
        )

        matrix = build_coverage_matrix(bank, context_id, plan=plan, pack=plan_pack.pack,
                                       scenarios=scenarios)
        store.write_coverage(bank, context_id, matrix, render_coverage_md(matrix))
        return coverage_summary(matrix)
    except Exception as exc:  # noqa: BLE001 — coverage is a best-effort overlay, never breaks implement
        log.warning("implement: coverage matrix skipped (%s)", exc)
        return ""


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
