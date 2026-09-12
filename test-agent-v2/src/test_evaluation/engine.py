"""The evaluation engine — score a persisted pack into a Pack Quality Score."""

from __future__ import annotations

from common.interrogate.pack import load_pack
from test_evaluation.metrics.entities import entities_recall
from test_evaluation.metrics.node_overlap import retrieval_scores
from test_evaluation.metrics.pqs import pqs
from test_evaluation.metrics.rubrics import cites_only_real_ids, no_invented_urls
from test_evaluation.models import EvalCase, EvalReport, PQSComponents, RubricsReport
from test_evaluation.monitoring import get_logger

log = get_logger("engine")


def _pack_view(bank, context_id: str):
    """The loaded pack + run-scoped node ids + per-node text (title + id) for this context."""
    pack = load_pack(bank, context_id)
    ids = {n.id for n in pack.notes}
    texts = [f"{n.title} {n.id}" for n in pack.notes]
    return pack, ids, texts


def evaluate_pack(bank, context_id: str, case: EvalCase | None = None) -> EvalReport:
    """Score the pack `context_id` gathered. `case` supplies the golden ground truth (relevant/"""
    pack, node_ids, node_texts = _pack_view(bank, context_id)
    understanding = bank.read_understanding(context_id) or ""

    retr = retrieval_scores(
        node_ids,
        set(case.relevant_node_ids) if case else set(),
        set(case.must_not_retrieve_ids) if case else set(),
    )
    ents = entities_recall(node_texts, case.key_entities if case else [])
    rub_ids = cites_only_real_ids(understanding, node_ids)
    rub_urls = no_invented_urls(understanding, pack.summary_text())

    components = PQSComponents(
        faithfulness=float(rub_ids.passed and rub_urls.passed),
        ctx_precision=retr.precision,
        ctx_recall=retr.recall,
        relevancy=ents.recall,
        trajectory=1.0,  # fixed placeholder — real trajectory is scored in the adk eval harness, not the live path
    )
    out = pqs(components)
    log.info("evaluate_pack %s: PQS=%s leaked=%s", context_id, out.pqs, retr.leaked)
    return EvalReport(
        context_id=context_id, seed=case.seed if case else "",
        pqs=out.pqs, components=out.components, retrieval=retr, entities=ents,
        rubrics=RubricsReport(cites_only_real_ids=rub_ids, no_invented_urls=rub_urls),
    )
