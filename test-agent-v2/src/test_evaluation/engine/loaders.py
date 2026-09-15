"""Data access for the eval engines (SRP: loading the persisted artifacts, NOT scoring them).

`pack.py` and `plan.py` compose the `metrics/` over whatever these loaders return, so the I/O shape
lives in one place and the scorers stay pure composition."""

from __future__ import annotations

from common.interrogate.pack import load_pack
from common.memory.bank import ROOT, _slug


def pack_view(bank, context_id: str):
    """The loaded pack + run-scoped node ids + per-node text (title + id) for this context."""
    pack = load_pack(bank, context_id)
    ids = {n.id for n in pack.notes}
    texts = [f"{n.title} {n.id}" for n in pack.notes]
    return pack, ids, texts


def plan_artifacts(bank, context_id: str):
    """The persisted TestPlan + brief + suite (scenarios/steps/test-data) + the pack it was built on."""
    d = f"{ROOT}/test-plan/{_slug(context_id)}"
    plan = bank.get_json(f"{d}/plan.json", None) or {}
    brief = bank.get_text(f"{d}/plan-brief.md") or ""
    scenarios = bank.get_json(f"{d}/scenarios.json", [])
    steps = bank.get_json(f"{d}/steps.json", [])
    test_data = bank.get_json(f"{d}/test-data.json", [])
    pack = load_pack(bank, context_id)
    return plan, brief, scenarios, steps, test_data, pack
