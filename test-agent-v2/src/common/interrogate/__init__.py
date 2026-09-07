"""Knowledge Refinement (Step 2) — interrogate the gathered pack, collect insight.

Turn a grounded context pack into ranked business/technical/QA questions, ingest
human answers over a multi-turn A2A dialogue, distill each into a provenance-carrying
insight note, and restate a confirmed understanding. See docs/PROPOSAL-KNOWLEDGE-REFINEMENT.md.
"""

from common.interrogate.answers import IngestResult, ingest
from common.interrogate.insight import assumption_from_self_answer, distill_answer
from common.interrogate.loop import (
    RefineResult,
    RefineSession,
    accept_recommendation,
    refine,
)
from common.interrogate.pack import Pack, load_pack
from common.interrogate.questions import RoundQuestions, build_round_questions, generate_round
from common.interrogate.understanding import restate

__all__ = [
    "IngestResult",
    "Pack",
    "RefineResult",
    "RefineSession",
    "RoundQuestions",
    "accept_recommendation",
    "assumption_from_self_answer",
    "build_round_questions",
    "distill_answer",
    "generate_round",
    "ingest",
    "load_pack",
    "refine",
    "restate",
]
