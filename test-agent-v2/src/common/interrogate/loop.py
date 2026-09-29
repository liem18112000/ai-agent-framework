"""The Knowledge Refinement loop — a resumable, multi-turn interrogation state machine."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict, replace

from common.env import env_int
from common.interrogate.answers import ingest
from common.interrogate.insight import assumption_from_self_answer, distill_answer
from common.interrogate.pack import load_pack
from common.interrogate.questions import generate_round
from common.interrogate.understanding import restate
from common.memory.serialize import question_from_dict
from common.models import (
    INSIGHT,
    ROUNDS,
    Insight,
    Note,
    Pack,
    Question,
    RefinementRun,
    RefineResult,
)
from common.monitoring import get_logger

log = get_logger("refine.loop")

Gatherer = Callable[[str], Awaitable[None]]

_DEFAULT_MAX_QUESTIONS = 50  # per-round open-question cap; overflow is DEFERRED not dropped


def _resolve_max_questions() -> int:
    """Per-round open-question cap: env ``REFINE_MAX_QUESTIONS`` (default 50). Raise it to surface more
    questions per round; there is no hard ceiling beyond this — extra questions just defer to later."""
    return max(1, env_int("REFINE_MAX_QUESTIONS", _DEFAULT_MAX_QUESTIONS))


def _resolve_max_rounds() -> int:
    """Re-seed passes when a caller doesn't specify: 1 under Turbo (shallower, faster), else 4."""
    from common.adk.config import turbo_on

    return 1 if turbo_on() else 4


class RefineSession:
    def __init__(
        self, bank, context_id: str, *, seed: str = "", rounds=ROUNDS, max_questions: int | None = None,
        max_rounds: int | None = None, generator=None, understander=None, gatherer: Gatherer | None = None,
        answered_by: str = "human", run_id: str = "refine", now: str = "",
    ) -> None:
        self.bank, self.context_id, self.rounds = bank, context_id, tuple(rounds)
        self.max_questions = max_questions if max_questions is not None else _resolve_max_questions()
        self.max_rounds = max_rounds if max_rounds is not None else _resolve_max_rounds()
        self.generator, self.understander, self.gatherer = generator, understander, gatherer
        self.answered_by, self.run_id, self.now = answered_by, run_id, now

        self.pack = load_pack(bank, context_id, seed=seed)
        self.insights: list[Insight] = []
        self.new_seeds: list[str] = []
        self._seen_seeds: set[str] = set()
        self._pending: list[str] = list(self.rounds)
        self._current: list[Question] = []
        self._pass, self._reseeded_this_pass, self._insights_this_pass = 1, False, 0
        self._deferred: list[Question] = []
        self._open_carried: list[Question] = []
        self._raised, self._answered = 0, 0

    def is_empty(self) -> bool:
        return self.pack.is_empty()

    def next_questions(self) -> list[Question] | None:
        """Advance to the next round with open questions, or None when the session is done."""
        while True:
            if not self._pending and not self._start_new_pass():
                return None
            rnd = self._pending.pop(0)
            qs = generate_round(self._pack_for_round(), rnd, max_questions=self.max_questions,
                                generator=self.generator)
            for q in qs:
                if q.status == "self-answered":
                    self._record_insight(assumption_from_self_answer(q, self.pack, run_id=self.run_id, now=self.now))
            self.bank.write_questions(self.context_id, qs)
            self._current = qs
            if open_qs := [q for q in qs if q.status == "open"]:
                self._raised += len(open_qs)
                log.info("pass %d round %s: %d open questions", self._pass, rnd, len(open_qs))
                return open_qs

    async def submit(self, raw) -> None:
        """Ingest answers for the current round, distill insights, re-ground on a new seed."""
        res = ingest(self._current, raw, now=self.now, answered_by=self.answered_by)
        self.bank.append_answers(self.context_id, res.answers)
        self._answered += len(res.answered)
        self._deferred += res.deferred
        self._open_carried += res.carried

        by_id = {q.id: q for q in self._current}
        seeds: list[str] = []
        for ans in res.answers:
            self._record_insight(distill_answer(ans, by_id[ans.question_id], self.pack, run_id=self.run_id, now=self.now))
            if ans.new_seed and ans.new_seed not in self._seen_seeds:
                seeds.append(ans.new_seed)
                self._seen_seeds.add(ans.new_seed)

        for seed in seeds:
            self.new_seeds.append(seed)
            if self.gatherer:
                log.info("re-seed: gathering %s", seed)
                await self.gatherer(seed)
                self._reseeded_this_pass = True
        if self._reseeded_this_pass:
            self.pack = load_pack(self.bank, self.context_id, seed=self.pack.seed)

    def finalize(self) -> RefineResult:
        understanding, confidence = restate(
            self.pack, self.insights, open_questions=self._open_carried, deferred=self._deferred,
            understander=self.understander,
        )
        self.bank.write_understanding(self.context_id, understanding)
        if self.insights:
            self.bank.update_index(self._add_insights)
        open_gaps = [q.question for q in self._open_carried]
        run = RefinementRun(
            run_id=self.run_id, context_id=self.context_id, seed=self.pack.seed, rounds=list(self.rounds),
            questions_raised=self._raised, questions_answered=self._answered, insights_written=len(self.insights),
            new_seeds=self.new_seeds, gaps=open_gaps, understanding_confidence=confidence,
            started=self.now, ended=self.now,
        )
        self.bank.append_refine_run_log(run)
        log.info("refine done: %d insights, %d gaps, %d re-seeds", len(self.insights), len(open_gaps), len(self.new_seeds))
        return RefineResult(understanding, confidence, self.insights, open_gaps, self.new_seeds, run)

    def save(self) -> None:
        self.bank.write_refine_state(self.context_id, self._state())

    def _state(self) -> dict:
        return {
            "seed": self.pack.seed, "rounds": list(self.rounds), "pending": self._pending,
            "pass": self._pass, "reseeded": self._reseeded_this_pass, "insights_this_pass": self._insights_this_pass,
            "seen_seeds": sorted(self._seen_seeds), "deferred": [asdict(q) for q in self._deferred],
            "open_carried": [asdict(q) for q in self._open_carried], "insight_ids": [i.id for i in self.insights],
            "raised": self._raised, "answered": self._answered, "max_questions": self.max_questions,
            "max_rounds": self.max_rounds, "answered_by": self.answered_by, "run_id": self.run_id,
            "now": self.now, "done": False,
        }

    @classmethod
    def rehydrate(cls, bank, context_id: str, *, generator=None, understander=None,
                  gatherer: Gatherer | None = None) -> RefineSession:
        st = bank.read_refine_state(context_id)
        self = cls(
            bank, context_id, seed=st.get("seed", ""), rounds=st.get("rounds", ROUNDS),
            max_questions=st.get("max_questions"), max_rounds=st.get("max_rounds", 4),
            generator=generator, understander=understander, gatherer=gatherer,
            answered_by=st.get("answered_by", "human"), run_id=st.get("run_id", "refine"),
            now=st.get("now", ""),
        )
        self._pending = list(st.get("pending", []))
        self._pass = st.get("pass", 1)
        self._reseeded_this_pass = st.get("reseeded", False)
        self._insights_this_pass = st.get("insights_this_pass", 0)
        self._seen_seeds = set(st.get("seen_seeds", []))
        self._deferred = [question_from_dict(d) for d in st.get("deferred", [])]
        self._open_carried = [question_from_dict(d) for d in st.get("open_carried", [])]
        self._raised, self._answered = st.get("raised", 0), st.get("answered", 0)
        self.insights = [ins for iid in st.get("insight_ids", []) if (ins := bank.read_insight(iid))]
        self._current = bank.read_questions(context_id)
        return self

    def _record_insight(self, insight: Insight) -> None:
        self.insights.append(insight)
        self._insights_this_pass += 1
        self.bank.upsert_insight(insight)

    def _start_new_pass(self) -> bool:
        """Begin another pass only if a re-seed enriched the pack, budget remains, and it wasn't dry."""
        if self._reseeded_this_pass and self._pass < self.max_rounds and self._insights_this_pass > 0:
            self._pass += 1
            self._pending = list(self.rounds)
            self._reseeded_this_pass = False
            self._insights_this_pass = 0
            log.info("starting refine pass %d", self._pass)
            return True
        return False

    def _pack_for_round(self) -> Pack:
        """The pack the round generator + critic see, overlaid with THIS session's committed insights
        as INSIGHT notes. Later rounds are told to 'build on the committed business answers', but those
        insights are only written to the graph at finalize and load_pack filters INSIGHT nodes out — so
        without this overlay the technical/QA rounds reason from decisions they cannot see. Rendered by
        summary_text's 'Already decided' section; a no-op (returns self.pack) when nothing's committed."""
        if not self.insights:
            return self.pack
        have = {n.id for n in self.pack.notes}
        extra = [Note(id=ins.id, type=INSIGHT, title=ins.statement[:200], synopsis=ins.rationale)
                 for ins in self.insights if ins.id not in have]
        return replace(self.pack, notes=[*self.pack.notes, *extra]) if extra else self.pack

    def _add_insights(self, graph) -> None:
        for ins in self.insights:
            graph.add_insight(ins)


def accept_recommendation(open_questions: list[Question]) -> dict:
    """Headless answer_fn: take the agent's recommendation for each open question."""
    return {q.id: q.recommendation for q in open_questions}


async def refine(
    bank, context_id: str, *, seed: str = "", rounds=ROUNDS,
    answer_fn: Callable[[list[Question]], object] | None = None,
    gatherer: Gatherer | None = None, answered_by: str = "human", **kw,
) -> RefineResult:
    """Run a full refine session end to end, sourcing answers from `answer_fn`."""
    session = RefineSession(bank, context_id, seed=seed, rounds=rounds, gatherer=gatherer, answered_by=answered_by, **kw)
    if session.is_empty():
        return RefineResult(understanding="Nothing to refine; run gather first.", confidence="low")
    answer_fn = answer_fn or accept_recommendation
    while (open_qs := session.next_questions()) is not None:
        await session.submit(answer_fn(open_qs))
    return session.finalize()
