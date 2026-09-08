"""Golden case loaders — one JSON per seed, the spec of "good" (kept in git)."""

from __future__ import annotations

import json
from pathlib import Path

_HERE = Path(__file__).parent


def _load(dirname: str) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((_HERE / dirname).glob("*.json"))]


def load_golden() -> list[dict]:
    return _load("golden")


def load_golden_plans() -> list[dict]:
    return _load("golden_plans")


def golden_for(ctx: str):
    """The golden pack EvalCase whose seed or fixture matches this context (best-effort)."""
    from test_evaluation.models import EvalCase
    for d in load_golden():
        if ctx in (d.get("seed"), d.get("fixture")):
            return EvalCase.from_dict(d)
    return None


def golden_plan_for(ctx: str):
    """The golden PlanEvalCase whose seed or fixture matches this context (best-effort)."""
    from test_evaluation.models import PlanEvalCase
    for d in load_golden_plans():
        if ctx in (d.get("seed"), d.get("fixture")):
            return PlanEvalCase.from_dict(d)
    return None
