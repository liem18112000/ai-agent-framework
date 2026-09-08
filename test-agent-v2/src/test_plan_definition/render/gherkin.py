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
        lines.append(f"  @{sc.kind} @{sc.methodology}")
        lines.append(f"  Scenario: {sc.title}")
        steps_sorted = sorted(by_scenario.get(sc.id, []), key=lambda s: s.order)
        has_keywords = any(s.keyword for s in steps_sorted)
        if sc.data_refs and not has_keywords:
            lines.append(f"    Given the test data ({', '.join(sc.data_refs)}) is prepared")
        for st in steps_sorted:
            if st.keyword:
                lines.append(f"    {st.keyword} {st.action}")
            else:
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
    subject = scenarios[0].title.split(" — ")[0]
    text = render_feature(subject, scenarios, steps)
    store.write_feature(bank, context_id, context_id, text)
    return text
