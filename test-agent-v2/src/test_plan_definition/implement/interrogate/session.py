"""The interrogative-implement loop (Q3/Q4) — a resumable multi-turn session that interrogates the
test-case / test-data / step-oracle design BEFORE generation, mirroring the define `PlanSession`.

Its distinctive effect: the `case-design` round's answer updates the confirmed plan's OPEN
`test_kinds` taxonomy, so the downstream generator covers exactly the kinds the user chose/added
(no fixed four, no cap). Data-design and step-oracle answers are recorded as provenance decisions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from common.interrogate.answers import ingest
from common.interrogate.questions import build_round_questions, generate_round
from common.interrogate.round.case_design import kinds_from_answer
from common.memory.serialize import question_from_dict
from common.testplan import memory as store
from common.testplan.models import CONFIRMED, PlanDecision, TestPlan
from common.testplan.pack import PlanPack, load_plan_pack
from test_plan_definition.define.decision import assumption_from_self_answer, decision_from_answer
from test_plan_definition.monitoring import get_logger

log = get_logger("implement.session")

IMPLEMENT_ROUNDS = ("case-design", "data-design", "step-oracle")
_IMPL_PREFIX = {"case-design": "cds", "data-design": "dds", "step-oracle": "sor"}


@dataclass
class ImplementBrief:
    """The result of an implement-interrogation pass — the kinds/methods now driving generation."""

    plan: TestPlan | None = None
    decisions: list[PlanDecision] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    brief: str = ""


class ImplementSession:
    def __init__(self, bank, context_id: str, *, plan: TestPlan | None = None,
                 plan_pack: PlanPack | None = None, seed: str = "", rounds=IMPLEMENT_ROUNDS,
                 max_questions: int = 7, generator=None, answered_by: str = "human",
                 run_id: str = "implement", now: str = "") -> None:
        self.bank, self.context_id, self.rounds = bank, context_id, tuple(rounds)
        self.max_questions, self.answered_by = max_questions, answered_by
        self.run_id, self.now = run_id, now
        self.plan = plan or store.read_plan(bank, context_id)
        self.plan_pack = plan_pack or load_plan_pack(bank, context_id, seed=seed)
        # heuristic-only question generator (offline-safe, no model calls) via the round registry
        self.generator = generator or (
            lambda pack, rnd: build_round_questions(pack, rnd, id_prefix=_IMPL_PREFIX[rnd]))

        self.decisions: list[PlanDecision] = []
        self._pending: list[str] = list(self.rounds)
        self._current: list = []
        self._open_carried: list = []
        self._kinds: list[str] = []
        self._raised = self._answered = 0

    def is_empty(self) -> bool:
        """Nothing to interrogate unless there is a CONFIRMED plan over a non-empty pack."""
        return self.plan is None or self.plan.status != CONFIRMED or self.plan_pack.is_empty()

    def next_questions(self):
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
                return open_qs
        return None

    async def submit(self, raw) -> None:
        res = ingest(self._current, raw, now=self.now, answered_by=self.answered_by)
        store.write_answers(self.bank, self.context_id, res.answers)
        self._answered += len(res.answered)
        self._open_carried += res.carried + res.deferred
        by_id = {q.id: q for q in self._current}
        for ans in res.answers:
            decision = decision_from_answer(
                ans, by_id[ans.question_id], self.plan_pack, run_id=self.run_id, now=self.now)
            self._record(decision)
            if decision.round == "case-design":
                self._kinds = kinds_from_answer(decision.chosen)

    def finalize(self) -> ImplementBrief:
        # The load-bearing effect: the elicited kinds override the plan's open taxonomy.
        if self.plan is not None and self._kinds:
            self.plan.test_kinds = self._kinds
            store.write_plan(self.bank, self.plan)
        store.write_implement_decisions(self.bank, self.context_id, self.decisions)
        brief = self._render_brief()
        store.write_implement_brief(self.bank, self.context_id, brief)
        store.write_implement_state(self.bank, self.context_id, {"done": True})
        log.info("implement interrogation done: %d decisions, kinds=%s", len(self.decisions),
                 self._kinds or "(defaults)")
        return ImplementBrief(self.plan, self.decisions, self._kinds, brief)

    def _render_brief(self) -> str:
        kinds = ", ".join(self._kinds) or "happy, negative, boundary, error (defaults)"
        methods = ", ".join(self.plan.test_design) if self.plan and self.plan.test_design else \
            "(per behaviour)"
        lines = [f"## Implement design brief — {self.context_id}", "",
                 f"**Test-design method(s):** {methods}", f"**Kinds to cover (open):** {kinds}", "",
                 "**Design decisions:**"]
        lines += [f"- [{d.round}] {d.statement}" for d in self.decisions] or ["- (none)"]
        return "\n".join(lines) + "\n"

    def save(self) -> None:
        store.write_implement_state(self.bank, self.context_id, self._state())

    def _state(self) -> dict:
        return {
            "seed": self.plan_pack.pack.seed, "rounds": list(self.rounds), "pending": self._pending,
            "open_carried": [asdict(q) for q in self._open_carried], "raised": self._raised,
            "answered": self._answered, "kinds": self._kinds, "max_questions": self.max_questions,
            "answered_by": self.answered_by, "run_id": self.run_id, "now": self.now, "done": False,
        }

    @classmethod
    def rehydrate(cls, bank, context_id: str, *, generator=None) -> ImplementSession:
        st = store.read_implement_state(bank, context_id)
        self = cls(bank, context_id, seed=st.get("seed", ""), rounds=st.get("rounds", IMPLEMENT_ROUNDS),
                   max_questions=st.get("max_questions", 7), generator=generator,
                   answered_by=st.get("answered_by", "human"), run_id=st.get("run_id", "implement"),
                   now=st.get("now", ""))
        self._pending = list(st.get("pending", []))
        self._open_carried = [question_from_dict(d) for d in st.get("open_carried", [])]
        self._kinds = list(st.get("kinds", []))
        self._raised, self._answered = st.get("raised", 0), st.get("answered", 0)
        self.decisions = store.read_implement_decisions(bank, context_id)
        self._current = store.read_questions(bank, context_id)
        return self

    def _record(self, decision: PlanDecision) -> None:
        self.decisions.append(decision)
        store.write_implement_decisions(self.bank, self.context_id, self.decisions)
