"""BDD / Gherkin quality — is the exported .feature well-formed? (deterministic tier)"""

from __future__ import annotations

from test_evaluation.models import GherkinReport


def gherkin_lint(feature_text: str) -> GherkinReport:
    lines = [ln.rstrip() for ln in (feature_text or "").splitlines()]
    issues: list[str] = []
    if not any(ln.startswith("Feature:") for ln in lines):
        issues.append("no Feature: header")

    scenarios = tagged = 0
    for i, ln in enumerate(lines):
        if ln.strip().startswith("Scenario:"):
            scenarios += 1
            prev = lines[i - 1].strip() if i else ""
            tags = [t for t in prev.split() if t.startswith("@")]
            if len(tags) >= 2:
                tagged += 1
            else:
                issues.append(f"scenario missing @kind @methodology tags: {ln.strip()[:60]}")

    has_steps = any(ln.strip().startswith(("When ", "Then ", "Given ", "And ")) for ln in lines)
    if scenarios and not has_steps:
        issues.append("no Given/When/Then steps")

    return GherkinReport(passed=not issues, scenarios=scenarios, tagged=tagged, issues=issues)
