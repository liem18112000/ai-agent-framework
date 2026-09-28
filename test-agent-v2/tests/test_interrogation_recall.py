"""L4 recall wiring (two-tier): the shared InterrogationAgent injects prior lessons into the pack
so refine/define don't re-learn them. `_recall_into` routes through the `common.memory.retrieve`
facade (hybrid under a DB backend, structural GCS otherwise) and is flag-gated (RECALL_LESSONS,
default off) so the default path is untouched. These drive the seam directly, offline (no Vertex/DB).
"""

from __future__ import annotations

import pytest

from common.adk.interrogation import _recall_into
from common.models import Note, Pack


def _pack() -> Pack:
    return Pack(
        context_id="run-1",
        notes=[
            Note(id="jira:LUZ-1", type="jira", title="Dunning cancellation"),
            Note(id="jira:LUZ-2", type="jira", title="Credit-only import"),
        ],
    )


@pytest.fixture
def spy(monkeypatch):
    calls: list[dict] = []

    async def fake_recall(bank, *, seed_refs, query_text="", limit=5, steps=()):
        calls.append({"seed_refs": set(seed_refs), "query_text": query_text,
                      "steps": steps})
        return ["Performance targets the credit-only operation, not file import"]

    monkeypatch.setattr("common.memory.retrieve.recall_lessons", fake_recall)
    return calls


async def test_recall_disabled_by_default_is_a_noop(monkeypatch, spy):
    monkeypatch.delenv("KGA_RECALL_LESSONS", raising=False)  # flag off → default path unchanged
    pack = _pack()
    await _recall_into(bank=None, pack=pack, prefix="KGA")
    assert spy == []            # the facade is never even called
    assert pack.lessons == []   # nothing injected


async def test_recall_enabled_injects_lessons_from_the_facade(monkeypatch, spy):
    monkeypatch.setenv("KGA_RECALL_LESSONS", "1")
    pack = _pack()
    await _recall_into(bank=None, pack=pack, prefix="KGA")
    assert len(spy) == 1
    assert spy[0]["seed_refs"] == {"jira:LUZ-1", "jira:LUZ-2"}          # grounded node ids → seeds
    # R1: the agent's own POSITION reaches the facade, so KGA leads with KGA-earned lessons.
    assert spy[0]["steps"] == ("gather", "refine")
    assert spy[0]["query_text"] == "Dunning cancellation Credit-only import"  # grounded titles
    assert pack.lessons == ["Performance targets the credit-only operation, not file import"]


async def test_recall_is_best_effort_on_error(monkeypatch):
    monkeypatch.setenv("TPD_RECALL_LESSONS", "1")

    async def boom(*a, **k):
        raise RuntimeError("pg down")

    monkeypatch.setattr("common.memory.retrieve.recall_lessons", boom)
    pack = _pack()
    await _recall_into(bank=None, pack=pack, prefix="TPD")  # must not raise
    assert pack.lessons == []   # left unchanged on failure
