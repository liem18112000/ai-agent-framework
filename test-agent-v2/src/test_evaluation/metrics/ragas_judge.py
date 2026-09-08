"""RAGAS generation metrics (LLM-judged) — Faithfulness + Response Relevancy over the understanding."""

from __future__ import annotations

import importlib.util

from test_evaluation.models import RagasScore


def available() -> bool:
    return importlib.util.find_spec("ragas") is not None


def judge(seed_summary: str, understanding: str, note_synopses: list[str], reference: str,
          *, llm=None, embeddings=None) -> RagasScore:
    """Score one {question, answer, contexts, reference} sample into a RagasScore."""
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
