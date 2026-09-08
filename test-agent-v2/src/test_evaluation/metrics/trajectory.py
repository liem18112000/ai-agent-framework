"""ADK `tool_trajectory_avg_score` — did the controller call the right tools in the right order?"""

from __future__ import annotations


def trajectory_score(actual: list[str], expected: list[str], mode: str = "in_order") -> float:
    """Score `actual` against `expected`. 1.0 = perfect. Empty expected → 1.0 (nothing required)."""
    if not expected:
        return 1.0
    if mode == "any_order":
        return len(set(expected) & set(actual)) / len(expected)
    if mode == "exact":
        return float(actual == expected)
    it = iter(actual)
    return float(all(e in it for e in expected))
