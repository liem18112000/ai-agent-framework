"""PlanPack — the input the define/implement stages read.

Reuses knowledge_gathering's grounded `Pack` (notes + link graph + gaps + recorded
insights) and adds the confirmed understanding brief that the refine stage restated —
together they are the "Collect insight" hand-off, keyed by `context_id`.
"""

from __future__ import annotations

from common.interrogate.pack import load_pack

# Re-exported so `from test_plan_definition.pack import PlanPack` keeps working.
from test_plan_definition.models import PlanPack


def load_plan_pack(bank, context_id: str, *, seed: str = "") -> PlanPack:
    """Read the approved insight pack + confirmed understanding for `context_id`."""
    return PlanPack(
        pack=load_pack(bank, context_id, seed=seed),
        understanding=bank.read_understanding(context_id) or "",
    )
