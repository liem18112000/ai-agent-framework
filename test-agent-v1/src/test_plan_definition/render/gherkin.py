"""Render generated scenarios/steps as BDD/Gherkin .feature files.

One Feature per plan; one Scenario per TestScenario, tagged @<kind> @<methodology>; each step
becomes a When/Then pair, with the test data as a Given. The structured scenarios/steps remain
the source of truth — this is a presentational export the downstream Test execution stage (and
the implement-bdd-steps skill) can consume.
"""

from __future__ import annotations

from test_plan_definition import memory as store
from test_plan_definition.models import TestScenario, TestStep


def render_feature(subject: str, scenarios: list[TestScenario], steps: list[TestStep]) -> str:
    by_scenario: dict[str, list[TestStep]] = {}
    for st in steps:
        by_scenario.setdefault(st.scenario_id, []).append(st)

    lines = [f"Feature: {subject}", ""]
    for sc in scenarios:
        lines.append(f"  @{sc.kind} @{sc.methodology}")
        lines.append(f"  Scenario: {sc.title}")
        steps_sorted = sorted(by_scenario.get(sc.id, []), key=lambda s: s.order)
        has_keywords = any(s.keyword for s in steps_sorted)
        # Only synthesize a data Given when the steps don't already carry BDD keywords.
        if sc.data_refs and not has_keywords:
            lines.append(f"    Given the test data ({', '.join(sc.data_refs)}) is prepared")
        for st in steps_sorted:
            if st.keyword:  # detailed step: the keyword + action is the Gherkin clause
                lines.append(f"    {st.keyword} {st.action}")
            else:  # legacy step: action -> assert pair
                lines.append(f"    When {st.action}")
                lines.append(f"    Then {st.expected}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def export_features(bank, context_id: str) -> str | None:
    """Write memory/test-plan/<ctx>/features/<ctx>.feature from the persisted scenarios/steps."""
    scenarios = store.read_scenarios(bank, context_id)
    if not scenarios:
        return None
    steps = store.read_steps(bank, context_id)
    subject = scenarios[0].title.split(" — ")[0]  # the entity, without the "— happy path" suffix
    text = render_feature(subject, scenarios, steps)
    store.write_feature(bank, context_id, context_id, text)
    return text
