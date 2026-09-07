"""Golden case loaders — one JSON per seed, the spec of "good" (kept in git).

`golden/` holds pack EvalCases (KGA scoring); `golden_plans/` holds plan PlanEvalCases (TPD scoring).
Both are plain dict loaders — the engines wrap them in the typed EvalCase / PlanEvalCase.
"""

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
