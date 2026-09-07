"""Generate the clarifying questions for one define round (methodology | scope | metrics).

The interrogation scaffolding (round strategies, pack preamble, id/round factory, ranking + the
per-round open-cap) is shared via common.interrogate — the three test-plan round strategies now
live in common.interrogate.round (methodology.py / scope.py / metrics.py). This module only wires
the make_generator seam: Claude-on-Vertex when configured, else the shared heuristic dispatcher
with the test-plan id prefix.
"""

from __future__ import annotations

from collections.abc import Callable

from common.interrogate.pack import Pack
from common.interrogate.questions import build_round_questions
from common.llm.vertex import vertex_config
from common.models import Question
from test_plan_definition.models import ROUND_PREFIX as _PREFIX
from test_plan_definition.monitoring import get_logger

log = get_logger("define.questions")

# A generator turns a pack + round name into candidate questions (same shape refine uses,
# so common.interrogate.generate_round can rank/cap them). Understanding is threaded via a closure.
Generator = Callable[[Pack, str], list[Question]]


def make_generator(understanding: str = "") -> Generator:
    """Select the generator: Claude-on-Vertex when VERTEX_* is configured, else the heuristic."""
    cfg = vertex_config()
    if cfg:
        proj, loc, model = cfg
        from test_plan_definition.llm.questions import claude_plan_questions

        def generator(pack: Pack, round_name: str) -> list[Question]:
            # LLM first; if it yields nothing (parse failure / truncation / a genuinely empty
            # round) fall back to the heuristic so a define round is never silently blank —
            # mirrors common.interrogate.questions.make_generator (the refine fix).
            qs = claude_plan_questions(
                pack, understanding, round_name, project=proj, location=loc, model=model)
            if not qs:
                log.warning(
                    "round %s: LLM returned no questions — using heuristic fallback", round_name)
                qs = heuristic_questions(pack, understanding, round_name)
            return qs

        return generator

    def generator(pack: Pack, round_name: str) -> list[Question]:
        return heuristic_questions(pack, understanding, round_name)

    return generator


def heuristic_questions(pack: Pack, understanding: str, round_name: str) -> list[Question]:
    """Derive plan judgement-calls from the pack via the shared interrogation scaffolding.

    `understanding` is accepted for signature parity with the Claude generator (which uses it);
    the heuristic derives everything from the pack structure. Ids use the test-plan ROUND_PREFIX,
    and the round strategies live in common.interrogate.round.
    """
    return build_round_questions(pack, round_name, id_prefix=_PREFIX[round_name])
