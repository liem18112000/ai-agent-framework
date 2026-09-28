"""R4 tests: the refine loop — rounds, insight persistence, re-seed closure, termination, gaps."""

from __future__ import annotations

import copy

from common.interrogate import RefineSession, refine
from common.interrogate.pack import Pack
from common.memory import MemoryBank
from common.models import Note, Question


def _gen(**by_round):
    """A generator returning FRESH question objects per round (real generators build new ones)."""
    return lambda pack, rnd: [copy.deepcopy(q) for q in by_round.get(rnd, [])]


def _q(qid, rnd="business", **kw):
    kw.setdefault("question", f"{qid}?")
    kw.setdefault("options", [{"label": "A", "implication": "x"}])
    kw.setdefault("recommendation", "A")
    return Question(id=qid, round=rnd, **kw)


async def test_full_pass_persists_insights_and_understanding(pack_bucket):
    bank = MemoryBank(pack_bucket)
    gen = _gen(
        business=[_q("Q-biz-1")],
        technical=[_q("Q-tech-1", "technical")],
        qa=[_q("Q-qa-1", "qa")],
    )
    result = await refine(bank, "run-6f2a", seed="LUZ-158390", generator=gen, understander=None)
    assert len(result.insights) == 3
    assert result.confidence in ("high", "medium")
    assert "Understanding" in bank.read_understanding("run-6f2a")
    graph, _ = bank.load_index()
    assert any(n["type"] == "insight" for n in graph.nodes.values())
    assert any("refine-" in k for k in pack_bucket.store)


async def test_self_answered_becomes_assumption_not_a_question(pack_bucket):
    bank = MemoryBank(pack_bucket)
    gen = _gen(business=[
        _q("Q-biz-1", status="self-answered"),
        _q("Q-biz-2"),
    ])
    session = RefineSession(bank, "run-6f2a", rounds=["business"], generator=gen)
    open_qs = session.next_questions()
    assert [q.id for q in open_qs] == ["Q-biz-2"]
    assert any(i.kind == "assumption" and i.answered_by == "agent-self" for i in session.insights)


async def test_reseed_triggers_gather_and_regrounds(pack_bucket):
    bank = MemoryBank(pack_bucket)
    gathered: list[str] = []

    async def gatherer(seed):
        gathered.append(seed)
        note = Note(id=seed, type="confluence-page", title="newly gathered")
        bank.upsert_note(note)
        bank.update_index(lambda g: g.add_note(note))

    gen = _gen(business=[_q("Q-biz-1")], technical=[], qa=[_q("Q-qa-1", "qa")])

    def answer_fn(open_qs):
        return {q.id: ("read it [seed:confluence:777]" if q.id == "Q-biz-1" else q.recommendation)
                for q in open_qs}

    result = await refine(bank, "run-6f2a", seed="LUZ-158390",
                          generator=gen, gatherer=gatherer, answer_fn=answer_fn)
    assert gathered == ["confluence:777"]
    assert "confluence:777" in result.new_seeds
    assert any(i.kind == "gap-seed" for i in result.insights)


async def test_carried_questions_become_declared_gaps(pack_bucket):
    bank = MemoryBank(pack_bucket)
    gen = _gen(business=[_q("Q-biz-1"), _q("Q-biz-2")])

    result = await refine(bank, "run-6f2a", rounds=["business"], generator=gen,
                          answer_fn=lambda qs: {"Q-biz-1": "A"})
    assert result.open_gaps == ["Q-biz-2?"]
    assert result.run.gaps == ["Q-biz-2?"]


async def test_max_rounds_bounds_reseed_loop(pack_bucket):
    bank = MemoryBank(pack_bucket)
    calls = {"n": 0}

    async def gatherer(seed):
        calls["n"] += 1
        note = Note(id=seed, type="confluence-page", title="g")
        bank.upsert_note(note)
        bank.update_index(lambda g: g.add_note(note))

    gen = _gen(business=[_q("Q-biz-1")])

    def answer_fn(open_qs):
        return {q.id: f"more [seed:confluence:{calls['n']}]" for q in open_qs}

    result = await refine(bank, "run-6f2a", rounds=["business"], max_rounds=3,
                          generator=gen, gatherer=gatherer, answer_fn=answer_fn)
    assert calls["n"] == 3
    assert len(result.new_seeds) == 3


async def test_empty_pack_short_circuits(fake_bucket):
    result = await refine(MemoryBank(fake_bucket), "empty-ctx")
    assert "run gather first" in result.understanding.lower()


def test_pack_dataclass_default_is_empty():
    assert Pack(context_id="x").is_empty()
