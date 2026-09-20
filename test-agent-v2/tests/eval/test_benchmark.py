"""Offline tests for run benchmarking — compute + cache-aside + compare + summarize (no network)."""

from __future__ import annotations

import pytest

from common.benchmark import read_benchmark
from common.memory import MemoryBank
from common.models import Note
from common.store.memory import InMemoryObjectStore
from test_evaluation import benchmark as bench
from test_evaluation.models import PlanReport, TPSComponents
from tests.conftest import drive_adk


def _bank() -> MemoryBank:
    return MemoryBank(InMemoryObjectStore())


def _seed_pack(bank: MemoryBank, ctx: str, n: int = 2) -> None:
    """A gathered pack of `n` notes owned by `ctx` (so load_pack(ctx) returns them)."""
    for i in range(n):
        note = Note(id=f"jira:{ctx}-{i}", type="jira-issue", title=f"Issue {i}", run_id=ctx, synopsis="body")
        bank.upsert_note(note)
        bank.update_index(lambda g, note=note: g.add_note(note))


def _seed_run(bank: MemoryBank, ctx: str, *, now: str) -> None:
    """A refine dir so the run is enumerable by summarize (memory/refine/<ctx>/)."""
    bank.write_refine_state(ctx, {"seed": ctx, "now": now, "done": True})


def test_compute_pack_only_scores_pqs_tps_none():
    bank = _bank()
    _seed_pack(bank, "run-1")
    bm = bench.compute_benchmark(bank, "run-1")
    assert bm.ok and bm.pqs is not None and bm.tps is None
    assert bm.retrieval is not None and "faithfulness" in bm.pqs_components


def test_load_or_compute_saves_the_record():
    bank = _bank()
    _seed_pack(bank, "run-1")
    assert read_benchmark(bank, "run-1") is None       # nothing cached yet
    bench.load_or_compute(bank, "run-1")
    assert read_benchmark(bank, "run-1") is not None    # computed + saved


def test_empty_run_is_a_failed_record_still_saved():
    bank = _bank()
    _seed_run(bank, "run-x", now="2026-01-01T00-00-00Z")  # refine state, but no pack, no plan
    bm = bench.load_or_compute(bank, "run-x")
    assert bm.ok is False and "nothing to score" in bm.error
    assert read_benchmark(bank, "run-x").ok is False       # the failed record is persisted


def test_cache_hit_skips_recompute_but_recompute_flag_forces_it(monkeypatch):
    bank = _bank()
    _seed_pack(bank, "run-1")
    first = bench.load_or_compute(bank, "run-1")

    def _boom(*a, **k):
        raise AssertionError("should not recompute on a cache hit")

    monkeypatch.setattr(bench, "compute_benchmark", _boom)
    second = bench.load_or_compute(bank, "run-1")           # served from cache — no recompute
    assert second.pqs == first.pqs
    with pytest.raises(AssertionError):                     # recompute=True bypasses the cache
        bench.load_or_compute(bank, "run-1", recompute=True)


def test_plan_path_populates_tps(monkeypatch):
    bank = _bank()
    _seed_pack(bank, "run-1")
    bank.put_json("memory/test-plan/run-1/plan.json", {"scope": []})  # makes _has_plan True
    monkeypatch.setattr(bench, "evaluate_plan",
                        lambda b, ctx, case=None, **k: PlanReport(context_id=ctx, tps=0.7,
                                                                  components=TPSComponents(coverage=0.5)))
    bm = bench.compute_benchmark(bank, "run-1")
    assert bm.tps == 0.7 and bm.tps_components["coverage"] == 0.5


def test_engine_error_is_captured_as_failed(monkeypatch):
    bank = _bank()
    _seed_pack(bank, "run-1")

    def _raise(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(bench, "evaluate_pack", _raise)
    bm = bench.compute_benchmark(bank, "run-1")
    assert bm.ok is False and "RuntimeError: boom" in bm.error


def test_compare_two_runs_table():
    bank = _bank()
    _seed_pack(bank, "run-a")
    _seed_pack(bank, "run-b")
    out = bench.compare(bank, ["run-a", "run-b"])
    assert "run-a" in out and "run-b" in out and "| PQS |" in out and "| Δ |" in out
    assert "at least two" in bench.compare(bank, ["run-a"])          # <2 ids rejected
    assert "at least two" in bench.compare(bank, ["run-a", "run-a"])  # dedupe → 1 → rejected


def test_summarize_newest_first_and_clamps_k():
    bank = _bank()
    for ctx, now in [("run-old", "2026-01-01T00-00-00Z"), ("run-new", "2026-02-01T00-00-00Z")]:
        _seed_pack(bank, ctx)
        _seed_run(bank, ctx, now=now)
    out = bench.summarize(bank, k=5)
    assert out.index("run-new") < out.index("run-old")  # newest first
    assert "**PQS**" in out and "**TPS**" in out
    assert "between 1 and 9" in bench.summarize(bank, k=0)  # K bounds enforced


# --- M3: the agent routes the benchmark verbs (send_raw_tev path) -----------------------------------

async def test_agent_routes_benchmark_verbs(monkeypatch):
    import test_evaluation.agent as agent_mod

    bank = _bank()
    for ctx, now in [("run-a", "2026-01-01T00-00-00Z"), ("run-b", "2026-02-01T00-00-00Z")]:
        _seed_pack(bank, ctx)
        _seed_run(bank, ctx, now=now)
    monkeypatch.setattr(agent_mod, "build_bank", lambda: bank)

    one = await drive_adk(agent_mod.build_root_agent, "benchmark run-a", session_id="run-a")
    assert "Benchmark run-a" in one and "PQS" in one

    cmp = await drive_adk(agent_mod.build_root_agent, "compare-benchmarks run-a run-b", session_id="s")
    assert "run-a" in cmp and "run-b" in cmp and "| PQS |" in cmp

    summ = await drive_adk(agent_mod.build_root_agent, "summarize-benchmarks 5", session_id="s")
    assert "Benchmark summary" in summ and "run-b" in summ


# --- M4: implement_plan fires the on_finish hook only on a terminal reply ---------------------------

class _FakeMCP:
    def tool(self):
        return lambda fn: fn


class _FakeSession:
    def __init__(self, reply: str = "", *, raises: bool = False):
        self._reply, self._raises, self.tasks = reply, raises, {}

    async def ask(self, text, **kw):
        if self._raises:
            raise RuntimeError("agent down")
        return type("R", (), {"text": self._reply, "state": "done",
                              "context_id": kw.get("context_id"), "task_id": None})()


async def _run_implement(reply: str = "", *, raises: bool = False):
    from test_plan_definition.bridge.mcp_server import register_tools

    fired: list[str] = []

    async def on_finish(ctx):
        fired.append(ctx)

    tools = register_tools(_FakeMCP(), _FakeSession(reply, raises=raises), on_finish=on_finish)
    try:
        await tools["implement_plan"]("run-1")
    except RuntimeError:
        pass
    return fired


async def test_finish_hook_fires_on_done():
    assert await _run_implement("[state: done] scenarios ready") == ["run-1"]


async def test_finish_hook_skips_in_progress_chunk():
    assert await _run_implement("[state: in_progress] round 1 of 3") == []


async def test_finish_hook_fires_on_error_even_though_it_raised():
    assert await _run_implement(raises=True) == ["run-1"]  # failed run still benchmarked
