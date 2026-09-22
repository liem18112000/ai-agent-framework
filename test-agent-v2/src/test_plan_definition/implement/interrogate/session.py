"""The interrogative-implement loop (Q3/Q4) — a resumable multi-turn session that interrogates the
test-case / test-data / step-oracle design BEFORE generation, mirroring the define `PlanSession`.

Both are thin ``RoundSession``s (``common/testplan/session.py``); ``ImplementSession`` adds its
distinctive effect: the `case-design` round's answer updates the confirmed plan's OPEN `test_kinds`
taxonomy (via the ``_on_decision`` hook + ``finalize``), so the downstream generator covers exactly
the kinds the user chose/added (no fixed four, no cap). Data-design and step-oracle answers are
recorded as provenance decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from common.interrogate.questions import build_round_questions
from common.interrogate.round.case_design import kinds_from_answer
from common.testplan import memory as store
from common.testplan.models import CONFIRMED, PlanDecision, TestPlan
from common.testplan.session import RoundSession
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


class ImplementSession(RoundSession):
    _RUN_ID = "implement"
    _ROUNDS = IMPLEMENT_ROUNDS
    _write_state = staticmethod(store.write_implement_state)
    _read_state = staticmethod(store.read_implement_state)
    _write_decisions = staticmethod(store.write_implement_decisions)
    _read_decisions = staticmethod(store.read_implement_decisions)

    def __init__(self, bank, context_id: str, *, plan: TestPlan | None = None, plan_pack=None,
                 seed: str = "", rounds=IMPLEMENT_ROUNDS, max_questions: int = 7, generator=None,
                 answered_by: str = "human", run_id: str = "implement", now: str = "") -> None:
        self.plan = plan or store.read_plan(bank, context_id)
        self._kinds: list[str] = []
        super().__init__(bank, context_id, plan_pack=plan_pack, seed=seed, rounds=rounds,
                         max_questions=max_questions, generator=generator, answered_by=answered_by,
                         run_id=run_id, now=now)

    def _default_generator(self):
        # heuristic-only question generator (offline-safe, no model calls) via the round registry
        return lambda pack, rnd: build_round_questions(pack, rnd, id_prefix=_IMPL_PREFIX[rnd])

    def is_empty(self) -> bool:
        """Nothing to interrogate unless there is a CONFIRMED plan over a non-empty pack."""
        return self.plan is None or self.plan.status != CONFIRMED or self.plan_pack.is_empty()

    def _on_decision(self, decision) -> None:
        # the case-design answer sets the kinds that will override the plan's open taxonomy
        if decision.round == "case-design":
            self._kinds = kinds_from_answer(decision.chosen)

    def _extra_state(self) -> dict:
        return {"kinds": self._kinds}

    def _restore_extra(self, st: dict) -> None:
        self._kinds = list(st.get("kinds", []))

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

    @classmethod
    def rehydrate(cls, bank, context_id: str, *, generator=None) -> ImplementSession:
        return cls._rehydrate(bank, context_id, generator=generator)
