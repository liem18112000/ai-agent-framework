"""Human Markdown rendering for the Test-Plan artifacts (plan, run-log).

The document shapes live in template.py; each renderer computes the dynamic parts (bullet
bodies) and fills the matching template. Write-only/presentational — read-back goes through
the JSON sidecar (writers.read_plan), never this output. Mirrors common.memory.render.
"""

from __future__ import annotations

from test_plan_definition.memory import template as tmpl
from test_plan_definition.models import TestPlan, TestPlanRun, TestScenario, TestStep


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) or "- (none)"


def render_plan_md(plan: TestPlan) -> str:
    return tmpl.PLAN_MD.format(
        context_id=plan.context_id,
        status=plan.status,
        confidence=plan.confidence,
        methodology=_bullets(plan.methodology),
        scope=_bullets(plan.scope),
        out_of_scope=_bullets(plan.out_of_scope),
        metrics=_bullets(plan.metrics),
        source_refs=_bullets(plan.source_refs),
    )


def render_scenarios_md(context_id: str, scenarios: list[TestScenario],
                        steps: list[TestStep]) -> str:
    by_scenario: dict[str, list[TestStep]] = {}
    for st in steps:
        by_scenario.setdefault(st.scenario_id, []).append(st)

    blocks = []
    for sc in scenarios:
        lines = [
            f"### {sc.title}  `[{sc.kind}/{sc.methodology}]`",
            f"- id: {sc.id}",
            f"- covers: {', '.join(sc.source_refs) or '-'}",
            f"- data: {', '.join(sc.data_refs) or '-'}",
            "",
            "Steps:",
        ]
        for st in sorted(by_scenario.get(sc.id, []), key=lambda s: s.order):
            lines.append(f"  {st.order}. {st.action} -> _{st.expected}_")
        blocks.append("\n".join(lines))
    return tmpl.SCENARIOS_MD.format(context_id=context_id, body="\n\n".join(blocks) or "(none)")


def render_run_log_md(run: TestPlanRun) -> str:
    return tmpl.PLAN_RUN_LOG_MD.format(
        run_id=run.run_id,
        context_id=run.context_id,
        plan_id=run.plan_id,
        rounds=", ".join(run.rounds),
        questions_raised=run.questions_raised,
        questions_answered=run.questions_answered,
        decisions_written=run.decisions_written,
        scenarios_written=run.scenarios_written,
        steps_written=run.steps_written,
        testdata_written=run.testdata_written,
        confidence=run.confidence,
        gaps=", ".join(run.gaps) or "(none)",
        started=run.started,
        ended=run.ended,
    )
