"""RAGAS generation metrics (LLM-judged) — Faithfulness + Response Relevancy over the understanding."""

from __future__ import annotations

import importlib.util

from test_evaluation.models import RagasScore


def available() -> bool:
    return importlib.util.find_spec("ragas") is not None


def judge(seed_summary: str, understanding: str, note_synopses: list[str], reference: str,
          *, llm=None, embeddings=None) -> RagasScore:
    """Score one {question, answer, contexts, reference} sample into a RagasScore.

    The `llm` and `embeddings` MUST be provider-sourced (I8, V1): passing `None` would let RAGAS
    fall back to its OpenAI default, so we refuse it up front (before importing ragas). Build them
    via `eval.judge.build_ragas_llm()` / `build_ragas_embeddings()`.
    """
    if llm is None or embeddings is None:
        raise ValueError(
            "ragas_judge.judge requires a provider-sourced llm AND embeddings (I8); refusing "
            "RAGAS's OpenAI default. Build them via eval.judge.build_ragas_llm() / "
            "build_ragas_embeddings()."
        )
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
