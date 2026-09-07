"""Executability / validity — are the suite artifacts real or placeholders? (deterministic)

The TPD heuristic path leaves tell-tale tokens (`<generated>`/`<expected>`/`<test-tenant>` in the
test-data spec, `PASS_METRIC` if a step's end-state never resolved) and `_KIND_SUFFIX` scenario
titles ("— happy path"). A `detail=True` run that still ships these has silently fallen back to the
heuristic — the TPD analog of the KGA fabrication guard. Deterministic scan over the persisted form.
"""

from __future__ import annotations

import json

from test_evaluation.models import PlaceholderReport

_TOKENS = ("<generated>", "<expected>", "<test-tenant>", "PASS_METRIC")
# a title ending in one of these is the heuristic scenario generator's signature (implement/scenarios.py)
_KIND_SUFFIXES = ("— happy path", "— negative", "— boundary", "— error")


def placeholder_scan(scenarios: list[dict], steps: list[dict], test_data: list[dict],
                     *, detail: bool = False) -> PlaceholderReport:
    """On the heuristic path these tokens are EXPECTED (mock placeholders) — not a defect. The leak
    gate only bites on a `detail=True` run, where the LLM should have resolved them: then a leaked
    token OR a heuristic provenance (silent fallback) is a fail. `leaked_tokens` is always reported."""
    blob = json.dumps([scenarios, steps, test_data], ensure_ascii=False)
    leaked = [t for t in _TOKENS if t in blob]

    titles = " ".join(sc.get("title", "") for sc in scenarios)
    provenance = "heuristic" if any(suf in titles for suf in _KIND_SUFFIXES) else "llm"

    passed = not (detail and (leaked or provenance == "heuristic"))
    return PlaceholderReport(passed=passed, leaked_tokens=leaked, provenance=provenance)
