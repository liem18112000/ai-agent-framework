"""Offline TPD harness — drive gather -> refine -> define -> implement in-process (no net, no LLM).

Builds on the KGA harness (`harness.py`): reuse its recorded-Atlassian gather + heuristic refine to
produce a real approved pack, then run the Test-Plan agent's `define` (headless, accept_recommendation)
and `implement_plan` over the SAME FakeBucket bank. Imports test_plan_definition, so it stays test-side
(keeps `test_evaluation` free of cross-agent deps — like harness.py imports knowledge_gathering).

A `PlanTrace` exposes the persisted suite in the dict form the metrics read (`dataclasses.asdict`),
so the harness and the runtime engine score the SAME shapes.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass

from common.memory import MemoryBank
from test_plan_definition.define import define
from test_plan_definition.implement import implement_plan
from tests.eval.harness import recorded_client, run_gather_offline, run_refine_offline


@dataclass
class PlanTrace:
    """What a human reviews after a define+implement: the plan, brief, and the persisted suite."""

    seed: str
    ctx: str
    bank: MemoryBank
    plan_result: object  # test_plan_definition PlanResult
    result: object       # test_plan_definition ImplementResult

    @property
    def plan(self):
        return self.plan_result.plan

    @property
    def brief(self) -> str:
        return self.plan_result.brief

    @property
    def feature(self) -> str:
        return self.result.feature

    @property
    def scenarios(self) -> list[dict]:
        return [asdict(s) for s in self.result.scenarios]

    @property
    def steps(self) -> list[dict]:
        return [asdict(s) for s in self.result.steps]

    @property
    def test_data(self) -> list[dict]:
        return [asdict(d) for d in self.result.test_data]

    @property
    def trajectory(self) -> list[str]:
        """The outer tool sequence actually driven (define -> approve -> implement)."""
        return ["define_plan", "approve_plan", "implement_plan"]


def run_define_offline(bank: MemoryBank, ctx: str, *, seed: str = ""):
    """Run the define interrogation to completion headlessly (accept_recommendation, no LLM)."""
    return asyncio.run(define(bank, ctx, seed=seed or ctx))


def run_implement_offline(bank: MemoryBank, ctx: str, *, detail: bool = False):
    return implement_plan(bank, ctx, run_id="eval", now="", detail=detail)


def run_plan_offline(seed: str, fixture: str, *, ctx: str | None = None, depth: int = 1) -> PlanTrace:
    """Full offline pipeline for one golden seed: gather -> refine -> define -> implement.

    The crawl stamps each note with run_id == ctx (B0 run-scoping), so define/implement/the engine
    all key off the SAME ctx."""
    ctx = ctx or f"eval-{seed}"
    t = run_gather_offline(seed, client=recorded_client(fixture),
                           text=f"gather {seed} depth {depth}", context_id=ctx)
    run_refine_offline(t.bank, ctx, seed=f"jira:{seed}")
    pr = run_define_offline(t.bank, ctx, seed=f"jira:{seed}")
    res = run_implement_offline(t.bank, ctx)
    return PlanTrace(seed=seed, ctx=ctx, bank=t.bank, plan_result=pr, result=res)
