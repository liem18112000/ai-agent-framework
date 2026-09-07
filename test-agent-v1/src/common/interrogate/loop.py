"""The Knowledge Refinement loop — a resumable, multi-turn interrogation state machine.

`RefineSession` advances one interrogation round at a time: it generates questions,
persists agent self-answers as assumptions, and pauses on the open ones. The caller
submits human answers; the session distills each into an insight, re-grounds the pack
when an answer names a new source (the Gather↔Refine edge), and moves on. It concludes
on a round budget, a dry pass, or when no open question remains — leftover questions are
declared as gaps, never dropped.

`RefineSession` is what the A2A executor drives (pause = input-required). `refine()` is a
thin synchronous driver over it for offline runs and tests.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict

from common.interrogate.answers import ingest
from common.interrogate.insight import assumption_from_self_answer, distill_answer
from common.interrogate.pack import load_pack
from common.interrogate.questions import generate_round
from common.interrogate.understanding import restate
from common.memory.serialize import question_from_dict
from common.models import ROUNDS, Insight, Question, RefinementRun, RefineResult
from common.monitoring import get_logger

log = get_logger("refine.loop")

# Re-grounds the pack for a new seed (in prod: run the gather crawl). Async — it may hit the network.
Gatherer = Callable[[str], Awaitable[None]]


class RefineSession:
    def __init__(
        self,
        bank,
        context_id: str,
        *,
        seed: str = "",
        rounds=ROUNDS,
        max_questions: int = 7,
        max_rounds: int = 4,
        generator=None,
        understander=None,
        gatherer: Gatherer | None = None,
        answered_by: str = "human",
        run_id: str = "refine",
        now: str = "",
    ) -> None:
        self.bank = bank
        self.context_id = context_id
        self.rounds = tuple(rounds)
        self.max_questions = max_questions
        self.max_rounds = max_rounds
        self.generator = generator
        self.understander = understander
        self.gatherer = gatherer
        self.answered_by = answered_by
        self.run_id = run_id
        self.now = now

        self.pack = load_pack(bank, context_id, seed=seed)
        self.insights: list[Insight] = []
        self.new_seeds: list[str] = []
        self._seen_seeds: set[str] = set()  # dedup: never re-gather the same source twice
        self._pending: list[str] = list(self.rounds)  # sub-rounds left in the current pass
        self._current: list[Question] = []
        self._pass = 1
        self._reseeded_this_pass = False
        self._insights_this_pass = 0
        self._deferred: list[Question] = []
        self._open_carried: list[Question] = []
        self._raised = 0
        self._answered = 0

    def is_empty(self) -> bool:
        return self.pack.is_empty()

    def next_questions(self) -> list[Question] | None:
        """Advance to the next round with open questions, or None when the session is done."""
        while True:
            if not self._pending and not self._start_new_pass():
                return None
            rnd = self._pending.pop(0)
            qs = generate_round(
                self.pack, rnd, max_questions=self.max_questions, generator=self.generator
            )
            for q in qs:  # persist agent self-answers as vetoable assumptions right away
                if q.status == "self-answered":
                    self._record_insight(assumption_from_self_answer(
                        q, self.pack, run_id=self.run_id, now=self.now))
            self.bank.write_questions(self.context_id, qs)
            self._current = qs
            open_qs = [q for q in qs if q.status == "open"]
            if open_qs:
                self._raised += len(open_qs)
                log.info("pass %d round %s: %d open questions", self._pass, rnd, len(open_qs))
                return open_qs

    async def submit(self, raw) -> None:
        """Ingest answers for the current round, distill insights, re-ground on a new seed."""
        res = ingest(self._current, raw, now=self.now, answered_by=self.answered_by)
        self.bank.append_answers(self.context_id, res.answers)
        self._answered += len(res.answered)
        self._deferred += res.deferred
        self._open_carried += res.carried  # carried → declared gaps (not re-queued: avoids looping)

        by_id = {q.id: q for q in self._current}
        seeds: list[str] = []
        for ans in res.answers:
            self._record_insight(distill_answer(
                ans, by_id[ans.question_id], self.pack, run_id=self.run_id, now=self.now))
            if ans.new_seed and ans.new_seed not in self._seen_seeds:
                seeds.append(ans.new_seed)
                self._seen_seeds.add(ans.new_seed)

        for seed in seeds:  # Gather↔Refine edge: re-ground before the next round (deduped)
            self.new_seeds.append(seed)
            if self.gatherer:
                log.info("re-seed: gathering %s", seed)
                await self.gatherer(seed)
                self._reseeded_this_pass = True
        if self._reseeded_this_pass:
            self.pack = load_pack(self.bank, self.context_id, seed=self.pack.seed)

    def finalize(self) -> RefineResult:
        understanding, confidence = restate(
            self.pack, self.insights,
            open_questions=self._open_carried, deferred=self._deferred,
            understander=self.understander,
        )
        self.bank.write_understanding(self.context_id, understanding)
        if self.insights:  # one batched CAS index write for the whole session
            self.bank.update_index(self._add_insights)
        open_gaps = [q.question for q in self._open_carried]
        run = RefinementRun(
            run_id=self.run_id, context_id=self.context_id, seed=self.pack.seed,
            rounds=list(self.rounds), questions_raised=self._raised,
            questions_answered=self._answered, insights_written=len(self.insights),
            new_seeds=self.new_seeds, gaps=open_gaps,
            understanding_confidence=confidence, started=self.now, ended=self.now,
        )
        self.bank.append_refine_run_log(run)
        log.info("refine done: %d insights, %d gaps, %d re-seeds",
                 len(self.insights), len(open_gaps), len(self.new_seeds))
        return RefineResult(understanding, confidence, self.insights, open_gaps, self.new_seeds, run)

    # --- resumable state (persisted so a stateless A2A turn can rehydrate) --- #
    def save(self) -> None:
        self.bank.write_refine_state(self.context_id, self._state())

    def _state(self) -> dict:
        return {
            "seed": self.pack.seed,
            "rounds": list(self.rounds),
            "pending": self._pending,
            "pass": self._pass,
            "reseeded": self._reseeded_this_pass,
            "insights_this_pass": self._insights_this_pass,
            "seen_seeds": sorted(self._seen_seeds),
            "deferred": [asdict(q) for q in self._deferred],
            "open_carried": [asdict(q) for q in self._open_carried],
            "insight_ids": [i.id for i in self.insights],
            "raised": self._raised,
            "answered": self._answered,
            "max_questions": self.max_questions,
            "max_rounds": self.max_rounds,
            "answered_by": self.answered_by,
            "run_id": self.run_id,
            "now": self.now,
            "done": False,
        }

    @classmethod
    def rehydrate(cls, bank, context_id: str, *, generator=None, understander=None,
                  gatherer: Gatherer | None = None) -> RefineSession:
        st = bank.read_refine_state(context_id)
        self = cls(
            bank, context_id, seed=st.get("seed", ""), rounds=st.get("rounds", ROUNDS),
            max_questions=st.get("max_questions", 7), max_rounds=st.get("max_rounds", 4),
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
        self._raised = st.get("raised", 0)
        self._answered = st.get("answered", 0)
        self.insights = [ins for iid in st.get("insight_ids", []) if (ins := bank.read_insight(iid))]
        self._current = bank.read_questions(context_id)  # the round now awaiting answers
        return self

    # --- internals --- #
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

    def _add_insights(self, graph) -> None:
        for ins in self.insights:
            graph.add_insight(ins)


def accept_recommendation(open_questions: list[Question]) -> dict:
    """Headless answer_fn: take the agent's recommendation for each open question."""
    return {q.id: q.recommendation for q in open_questions}


async def refine(
    bank,
    context_id: str,
    *,
    seed: str = "",
    rounds=ROUNDS,
    answer_fn: Callable[[list[Question]], object] | None = None,
    gatherer: Gatherer | None = None,
    answered_by: str = "human",
    **kw,
) -> RefineResult:
    """Run a full refine session end to end, sourcing answers from `answer_fn`."""
    session = RefineSession(
        bank, context_id, seed=seed, rounds=rounds, gatherer=gatherer,
        answered_by=answered_by, **kw,
    )
    if session.is_empty():
        return RefineResult(understanding="Nothing to refine; run gather first.", confidence="low")
    answer_fn = answer_fn or accept_recommendation
    while (open_qs := session.next_questions()) is not None:
        await session.submit(answer_fn(open_qs))
    return session.finalize()
