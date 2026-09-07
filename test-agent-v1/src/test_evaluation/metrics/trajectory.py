"""ADK `tool_trajectory_avg_score` — did the controller call the right tools in the right order?

Deterministic (no LLM): compares an actual call sequence to the golden expected one. Mirrors
ADK's three match modes. Used for both the outer MCP sequence (gather→refine→approve) and the
inner tier/fetch-kind order — the most regression-prone, most deterministic KGA surface.
"""

from __future__ import annotations


def trajectory_score(actual: list[str], expected: list[str], mode: str = "in_order") -> float:
    """Score `actual` against `expected`. 1.0 = perfect. Empty expected → 1.0 (nothing required).

    exact     — sequences identical.
    in_order  — every expected item appears in order (subsequence); extras allowed.
    any_order — fraction of expected items present, order ignored.
    """
    if not expected:
        return 1.0
    if mode == "any_order":
        return len(set(expected) & set(actual)) / len(expected)
    if mode == "exact":
        return float(actual == expected)
    it = iter(actual)  # in_order: expected must be a subsequence of actual
    return float(all(e in it for e in expected))
