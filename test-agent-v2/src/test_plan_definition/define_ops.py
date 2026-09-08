"""TPD define domain logic — framework-neutral (extracted from executor/define.py in C2)."""

from __future__ import annotations

import json

from test_plan_definition.define.loop import PlanResult


def wants_define(text: str) -> bool:
    t = text.strip().lower()
    if t.startswith("define"):
        return True
    if t.startswith("{"):
        try:
            return "context_id" in json.loads(text)
        except json.JSONDecodeError:
            return False
    return False


def summarize_define(result: PlanResult) -> str:
    status = result.plan.status if result.plan else "n/a"
    lines = [
        (
            f"Plan definition complete (status: {status}, confidence: {result.confidence}). "
            f"{len(result.decisions)} decisions, {len(result.open_gaps)} open gaps."
        ),
        "",
        result.brief.strip(),
    ]
    if result.open_gaps:
        lines += ["", "Declared gaps: " + "; ".join(result.open_gaps)]
    return "\n".join(lines)
