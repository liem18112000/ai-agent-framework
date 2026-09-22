"""Knowledge Refinement (Step 2) — interrogate the gathered pack, collect insight."""

from common.interrogate.answers import IngestResult, ingest
from common.interrogate.insight import assumption_from_self_answer, distill_answer
from common.interrogate.loop import RefineResult, RefineSession, accept_recommendation, refine
from common.interrogate.pack import Pack, load_pack
from common.interrogate.questions import build_round_questions, generate_round
from common.interrogate.understanding import restate

__all__ = [
    "IngestResult", "Pack", "RefineResult", "RefineSession",
    "accept_recommendation", "assumption_from_self_answer", "build_round_questions",
    "distill_answer", "generate_round", "ingest", "load_pack", "refine", "restate",
]
