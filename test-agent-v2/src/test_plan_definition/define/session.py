"""The Test Plan definition loop — a resumable, multi-turn reconfirm state machine."""

from __future__ import annotations

from dataclasses import asdict

from common.interrogate.answers import ingest
from common.interrogate.loop import accept_recommendation
from common.interrogate.questions import generate_round
from common.memory.serialize import question_from_dict
from common.testplan import memory as store
from common.testplan.models import (
    CONFIRMED,
    DRAFT,
    ROUNDS,
    PlanDecision,
    PlanResult,
    TestPlanRun,
)
from common.testplan.pack import PlanPack, load_plan_pack
from test_plan_definition.define.decision import assumption_from_self_answer, decision_from_answer
from test_plan_definition.define.plan import assemble_plan, confidence, restate
from test_plan_definition.define.questions import make_generator
from test_plan_definition.monitoring import get_logger

log = get_logger("define.session")


class PlanSession:
    def __init__(self, bank, context_id: str, *, plan_pack: PlanPack | None = None, seed: str = "",
                rounds=ROUNDS, max_questions: int = 7, generator=None, restater=None,
                answered_by: str = "human", run_id: str = "plan", now: str = "") -> None:
        self.bank, self.context_id, self.rounds = bank, context_id, tuple(rounds)
        self.max_questions, self.restater, self.answered_by = max_questions, restater, answered_by
        self.run_id, self.now = run_id, now
        self.plan_pack = plan_pack or load_plan_pack(bank, context_id, seed=seed)
        self.generator = generator or make_generator(self.plan_pack.understanding)

        self.decisions: list[PlanDecision] = []
        self._pending: list[str] = list(self.rounds)
        self._current: list = []
        self._open_carried: list = []
        self._raised = self._answered = 0

    def is_empty(self) -> bool:
        return self.plan_pack.is_empty()

    def next_questions(self):
        """Advance to the next round with open questions, or None when the session is done."""
        while self._pending:
            rnd = self._pending.pop(0)
            qs = generate_round(self.plan_pack.pack, rnd, max_questions=self.max_questions,
                                generator=self.generator)
            for q in qs:
                if q.status == "self-answered":
                    self._record(assumption_from_self_answer(
                        q, self.plan_pack, run_id=self.run_id, now=self.now))
            store.write_questions(self.bank, self.context_id, qs)
            self._current = qs
            if open_qs := [q for q in qs if q.status == "open"]:
                self._raised += len(open_qs)
                log.info("round %s: %d open questions", rnd, len(open_qs))
                return open_qs
        return None

    async def submit(self, raw) -> None:
        """Ingest answers for the current round and distill each into a PlanDecision."""
        res = ingest(self._current, raw, now=self.now, answered_by=self.answered_by)
        store.write_answers(self.bank, self.context_id, res.answers)
        self._answered += len(res.answered)
        self._open_carried += res.carried + res.deferred
        by_id = {q.id: q for q in self._current}
        for ans in res.answers:
            self._record(decision_from_answer(
                ans, by_id[ans.question_id], self.plan_pack, run_id=self.run_id, now=self.now))

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

    def save(self) -> None:
        store.write_plan_state(self.bank, self.context_id, self._state())

    def _state(self) -> dict:
        return {
            "seed": self.plan_pack.pack.seed, "rounds": list(self.rounds), "pending": self._pending,
            "open_carried": [asdict(q) for q in self._open_carried], "raised": self._raised,
            "answered": self._answered, "max_questions": self.max_questions,
            "answered_by": self.answered_by, "run_id": self.run_id, "now": self.now, "done": False,
        }

    @classmethod
    def rehydrate(cls, bank, context_id: str, *, generator=None, restater=None) -> PlanSession:
        st = store.read_plan_state(bank, context_id)
        self = cls(bank, context_id, seed=st.get("seed", ""), rounds=st.get("rounds", ROUNDS),
                   max_questions=st.get("max_questions", 7), generator=generator, restater=restater,
                   answered_by=st.get("answered_by", "human"), run_id=st.get("run_id", "plan"),
                   now=st.get("now", ""))
        self._pending = list(st.get("pending", []))
        self._open_carried = [question_from_dict(d) for d in st.get("open_carried", [])]
        self._raised, self._answered = st.get("raised", 0), st.get("answered", 0)
        self.decisions = store.read_decisions(bank, context_id)
        self._current = store.read_questions(bank, context_id)
        return self

    def _record(self, decision: PlanDecision) -> None:
        self.decisions.append(decision)
        store.write_decisions(self.bank, self.context_id, self.decisions)


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
