"""The Test Plan definition loop — a resumable, multi-turn reconfirm state machine.

``PlanSession`` is a thin ``RoundSession`` (``common/testplan/session.py``): it binds the ``plan`` +
``plan-decisions`` store surface and supplies the define-specific ``finalize`` (assemble → confirm the
``TestPlan``) / ``is_empty`` / question generator; the round/answer/checkpoint machinery is inherited.
"""

from __future__ import annotations

from common.interrogate.loop import accept_recommendation
from common.testplan import memory as store
from common.testplan.models import CONFIRMED, DRAFT, ROUNDS, PlanResult, TestPlanRun
from common.testplan.session import RoundSession
from test_plan_definition.define.plan import assemble_plan, confidence, restate
from test_plan_definition.define.questions import make_generator
from test_plan_definition.monitoring import get_logger

log = get_logger("define.session")


class PlanSession(RoundSession):
    _RUN_ID = "plan"
    _ROUNDS = ROUNDS
    _write_state = staticmethod(store.write_plan_state)
    _read_state = staticmethod(store.read_plan_state)
    _write_decisions = staticmethod(store.write_decisions)
    _read_decisions = staticmethod(store.read_decisions)

    def __init__(self, bank, context_id: str, *, plan_pack=None, seed: str = "", rounds=ROUNDS,
                 max_questions: int = 7, generator=None, restater=None, answered_by: str = "human",
                 run_id: str = "plan", now: str = "") -> None:
        self.restater = restater
        super().__init__(bank, context_id, plan_pack=plan_pack, seed=seed, rounds=rounds,
                         max_questions=max_questions, generator=generator, answered_by=answered_by,
                         run_id=run_id, now=now)

    def _default_generator(self):
        return make_generator(self.plan_pack.understanding)

    def is_empty(self) -> bool:
        return self.plan_pack.is_empty()

    def finalize(self) -> PlanResult:
        conf = confidence(self.decisions, self._open_carried)
        status = DRAFT if self._open_carried else CONFIRMED
        plan = assemble_plan(self.plan_pack, self.decisions, conf=conf, status=status,
                             run_id=self.run_id, now=self.now)
        store.write_plan(self.bank, plan)
        brief = restate(plan, self.plan_pack, self._open_carried, restater=self.restater)
        store.write_plan_brief(self.bank, self.context_id, brief)
        store.write_plan_state(self.bank, self.context_id, {"done": True})
        gaps = [q.question for q in self._open_carried]
        run = TestPlanRun(run_id=self.run_id, context_id=self.context_id, plan_id=plan.id,
                          rounds=list(self.rounds), questions_raised=self._raised,
                          questions_answered=self._answered, decisions_written=len(self.decisions),
                          gaps=gaps, confidence=conf, started=self.now, ended=self.now)
        store.append_plan_run_log(self.bank, run)
        log.info("define done: %d decisions, %d gaps, confidence %s",
                 len(self.decisions), len(gaps), conf)
        return PlanResult(plan, brief, self.decisions, gaps, conf, run)

    @classmethod
    def rehydrate(cls, bank, context_id: str, *, generator=None, restater=None) -> PlanSession:
        return cls._rehydrate(bank, context_id, generator=generator, restater=restater)


async def define(bank, context_id: str, *, seed: str = "", rounds=ROUNDS, answer_fn=None,
                 answered_by: str = "human", **kw) -> PlanResult:
    """Run a full define session end to end, sourcing answers from `answer_fn`."""
    session = PlanSession(bank, context_id, seed=seed, rounds=rounds, answered_by=answered_by, **kw)
    if session.is_empty():
        return PlanResult(brief="Nothing to plan; run gather + refine first.", confidence="low")
    answer_fn = answer_fn or accept_recommendation
    while (open_qs := session.next_questions()) is not None:
        await session.submit(answer_fn(open_qs))
    return session.finalize()
