"""Golden case loaders — one merged JSON per seed, the spec of "good" (kept in git).

Each golden file carries the shared identity (``seed``/``fixture``/``depth``, plus ``canary``/``max_score``
for canaries) at the top level and TWO view sub-objects: ``pack`` (KGA ground truth → ``EvalCase``) and
``plan`` (TPD ground truth → ``PlanEvalCase``). A single ``golden/`` dataset therefore anchors both
agents on the same seed, while the loaders below project a file into whichever view a scorer needs — so
``load_golden()`` / ``load_golden_plans()`` keep their original per-view shape for every caller. Canaries
(calibration) live under ``golden/canary/`` so the top-level ``*.json`` glob never picks them up."""

from __future__ import annotations

import json
from pathlib import Path

from test_evaluation.config.views import GOLDEN_VIEWS

_HERE = Path(__file__).parent


def _load(dirname: str) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((_HERE / dirname).glob("*.json"))]


def _project(d: dict, view: str) -> dict:
    """Flatten a merged golden file to one view: the shared top-level keys + the ``view`` sub-object."""
    return {**{k: v for k, v in d.items() if k not in GOLDEN_VIEWS}, **d.get(view, {})}


def _view(dirname: str, view: str) -> list[dict]:
    """Every merged golden file in `dirname`, projected to one `view` (files without it are skipped)."""
    return [_project(d, view) for d in _load(dirname) if view in d]


def load_golden() -> list[dict]:
    """The KGA pack ground truth (`pack` view of each golden seed)."""
    return _view("golden", "pack")


def load_golden_plans() -> list[dict]:
    """The TPD plan ground truth (`plan` view of each golden seed)."""
    return _view("golden", "plan")


def load_canaries() -> list[dict]:
    """Deliberately-bad pack cases (calibration) — the `pack` view of the merged canaries."""
    return _view("golden/canary", "pack")


def load_canary_plans() -> list[dict]:
    """Deliberately-bad plan cases (calibration) — the `plan` view of the merged canaries."""
    return _view("golden/canary", "plan")


def _case_for(ctx: str, cases: list[dict], model_cls):
    """The first golden case whose seed or fixture matches `ctx`, built as `model_cls` (best-effort)."""
    return next((model_cls.from_dict(d) for d in cases
                 if ctx in (d.get("seed"), d.get("fixture"))), None)


def golden_for(ctx: str):
    """The golden pack EvalCase whose seed or fixture matches this context (best-effort)."""
    from test_evaluation.models import EvalCase
    return _case_for(ctx, load_golden(), EvalCase)


def golden_plan_for(ctx: str):
    """The golden PlanEvalCase whose seed or fixture matches this context (best-effort)."""
    from test_evaluation.models import PlanEvalCase
    return _case_for(ctx, load_golden_plans(), PlanEvalCase)
