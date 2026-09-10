"""RoundSession — the shared resumable, multi-turn interrogation state machine behind the TPD
`define` (PlanSession) and `implement` (ImplementSession) loops.

It owns the machinery both share: walk the rounds, generate each round's questions (recording any
self-answered ones as assumptions), ingest a turn's answers into provenance ``PlanDecision`` records,
checkpoint to / rehydrate from the bank. Subclasses bind their **persistence surface** (the four
``store`` functions, as ``staticmethod`` class attrs) + the round taxonomy/run-id, and implement the
three genuinely-divergent pieces — ``_default_generator``, ``is_empty``, ``finalize`` — plus the
optional ``_on_decision`` / ``_extra_state`` / ``_restore_extra`` hooks for per-subclass state (e.g.
the implement loop's elicited ``kinds``). Lives in ``common/testplan`` (not ``common/interrogate``,
which is testplan-independent) so the dependency stays one-way.
"""

from __future__ import annotations

from dataclasses import asdict

from common.interrogate.answers import ingest
from common.interrogate.questions import generate_round
from common.memory.serialize import question_from_dict
from common.testplan import memory as store
from common.testplan.decision import assumption_from_self_answer, decision_from_answer
from common.testplan.pack import load_plan_pack


class RoundSession:
    # --- persistence surface + taxonomy: subclasses override these class attrs ---
    _RUN_ID = "session"
    _ROUNDS: tuple = ()
    _write_state = None       # staticmethod(store.write_<x>_state)
    _read_state = None        # staticmethod(store.read_<x>_state)
    _write_decisions = None   # staticmethod(store.write_<x>_decisions)
    _read_decisions = None    # staticmethod(store.read_<x>_decisions)

    def __init__(self, bank, context_id: str, *, plan_pack=None, seed: str = "", rounds=None,
                 max_questions: int = 7, generator=None, answered_by: str = "human",
                 run_id: str | None = None, now: str = "") -> None:
        self.bank, self.context_id = bank, context_id
        self.rounds = tuple(rounds if rounds is not None else self._ROUNDS)
        self.max_questions, self.answered_by = max_questions, answered_by
        self.run_id = run_id if run_id is not None else self._RUN_ID
        self.now = now
        self.plan_pack = plan_pack or load_plan_pack(bank, context_id, seed=seed)
        self.generator = generator or self._default_generator()

        self.decisions: list = []
        self._pending: list[str] = list(self.rounds)
        self._current: list = []
        self._open_carried: list = []
        self._raised = self._answered = 0

    # --- overridable hooks --------------------------------------------------------------------
    def _default_generator(self):
        """The round-question generator when none is injected (subclass-specific)."""
        raise NotImplementedError

    def is_empty(self) -> bool:
        """True when there is nothing to interrogate (subclass decides its precondition)."""
        raise NotImplementedError

    def finalize(self):
        """Assemble + persist the session's result (subclass-specific return type)."""
        raise NotImplementedError

    def _on_decision(self, decision) -> None:
        """React to each ingested (non-self) decision. Override to capture side-state."""

    def _extra_state(self) -> dict:
        """Extra keys merged into the checkpoint. Override to persist subclass state."""
        return {}

    def _restore_extra(self, st: dict) -> None:
        """Restore subclass state from a checkpoint. Override to mirror ``_extra_state``."""

    # --- shared machinery ---------------------------------------------------------------------
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
            decision = decision_from_answer(
                ans, by_id[ans.question_id], self.plan_pack, run_id=self.run_id, now=self.now)
            self._record(decision)
            self._on_decision(decision)

    def save(self) -> None:
        type(self)._write_state(self.bank, self.context_id, self._state())

    def _state(self) -> dict:
        return {
            "seed": self.plan_pack.pack.seed, "rounds": list(self.rounds), "pending": self._pending,
            "open_carried": [asdict(q) for q in self._open_carried], "raised": self._raised,
            "answered": self._answered, "max_questions": self.max_questions,
            "answered_by": self.answered_by, "run_id": self.run_id, "now": self.now, "done": False,
            **self._extra_state(),
        }

    def _record(self, decision) -> None:
        self.decisions.append(decision)
        type(self)._write_decisions(self.bank, self.context_id, self.decisions)

    @classmethod
    def _rehydrate(cls, bank, context_id: str, *, generator=None, **extra):
        """Rebuild a session from its checkpoint. Subclasses expose a thin ``rehydrate`` that calls
        this (passing any subclass-only ctor kwargs, e.g. ``restater``, through ``**extra``)."""
        st = cls._read_state(bank, context_id)
        self = cls(bank, context_id, seed=st.get("seed", ""), rounds=st.get("rounds") or cls._ROUNDS,
                   max_questions=st.get("max_questions", 7), generator=generator,
                   answered_by=st.get("answered_by", "human"), run_id=st.get("run_id", cls._RUN_ID),
                   now=st.get("now", ""), **extra)
        self._pending = list(st.get("pending", []))
        self._open_carried = [question_from_dict(d) for d in st.get("open_carried", [])]
        self._raised, self._answered = st.get("raised", 0), st.get("answered", 0)
        self.decisions = cls._read_decisions(bank, context_id)
        self._current = store.read_questions(bank, context_id)
        self._restore_extra(st)
        return self
