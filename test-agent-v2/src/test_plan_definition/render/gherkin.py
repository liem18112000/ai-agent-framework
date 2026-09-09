"""Render generated scenarios/steps as BDD/Gherkin .feature files."""

from __future__ import annotations

from test_plan_definition import memory as store
from test_plan_definition.models import TestScenario, TestStep


def render_feature(subject: str, scenarios: list[TestScenario], steps: list[TestStep]) -> str:
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
