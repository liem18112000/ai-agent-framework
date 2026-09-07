"""RAGAS generation metrics (LLM-judged) — Faithfulness + Response Relevancy over the understanding.

Faithfulness = fraction of the understanding's claims supported by the pack notes (same intent as
ADK hallucinations_v1). Response Relevancy = does it address THIS ticket. Both are LLM-judged and
non-deterministic → the caller samples and compares means to a baseline (never single-run pass/fail).

`ragas` is an optional [eval] extra; `available()` lets the judged tests skip cleanly without it.
The heavy imports live inside `judge()` so importing this module never requires ragas.
"""

from __future__ import annotations

import importlib.util

from test_evaluation.models import RagasScore


def available() -> bool:
    return importlib.util.find_spec("ragas") is not None


def judge(seed_summary: str, understanding: str, note_synopses: list[str], reference: str,
          *, llm=None, embeddings=None) -> RagasScore:
    """Score one {question, answer, contexts, reference} sample into a RagasScore.

    `llm`/`embeddings` are RAGAS-wrapped models (configure on Vertex, reuse common.llm); when None,
    RAGAS uses its process defaults. A judge family different from the generator is preferable.
    """
    from ragas import evaluate
    from ragas.dataset_schema import EvaluationDataset
    from ragas.metrics import answer_relevancy, faithfulness

    ds = EvaluationDataset.from_list([{
        "user_input": seed_summary,
        "response": understanding,
        "retrieved_contexts": note_synopses or [""],
        "reference": reference,
    }])
    kwargs = {k: v for k, v in (("llm", llm), ("embeddings", embeddings)) if v is not None}
    row = evaluate(ds, metrics=[faithfulness, answer_relevancy], **kwargs).to_pandas().iloc[0]
    return RagasScore(**{k: float(row[k]) for k in ("faithfulness", "answer_relevancy") if k in row})
