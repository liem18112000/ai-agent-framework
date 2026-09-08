"""PlanPack — the input the define/implement stages read."""

from __future__ import annotations

from common.interrogate.pack import load_pack
from test_plan_definition.models import PlanPack


def load_plan_pack(bank, context_id: str, *, seed: str = "") -> PlanPack:
    """Read the approved insight pack + confirmed understanding for `context_id`."""
    return PlanPack(
        pack=load_pack(bank, context_id, seed=seed),
        understanding=bank.read_understanding(context_id) or "",
    )
