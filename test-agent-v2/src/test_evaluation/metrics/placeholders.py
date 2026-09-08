"""Executability / validity — are the suite artifacts real or placeholders? (deterministic)"""

from __future__ import annotations

import json

from test_evaluation.models import PlaceholderReport

_TOKENS = ("<generated>", "<expected>", "<test-tenant>", "PASS_METRIC")
_KIND_SUFFIXES = ("— happy path", "— negative", "— boundary", "— error")


def placeholder_scan(scenarios: list[dict], steps: list[dict], test_data: list[dict],
                     *, detail: bool = False) -> PlaceholderReport:
    """On the heuristic path these tokens are EXPECTED (mock placeholders) — not a defect. The leak"""
    blob = json.dumps([scenarios, steps, test_data], ensure_ascii=False)
    leaked = [t for t in _TOKENS if t in blob]

    titles = " ".join(sc.get("title", "") for sc in scenarios)
    provenance = "heuristic" if any(suf in titles for suf in _KIND_SUFFIXES) else "llm"

    passed = not (detail and (leaked or provenance == "heuristic"))
    return PlaceholderReport(passed=passed, leaked_tokens=leaked, provenance=provenance)
