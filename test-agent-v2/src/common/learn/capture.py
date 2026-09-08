"""Self-learning capture (L1): distil per-step signals into cited, deduped Insight lessons."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

from common.learn.model import LessonSignal
from common.models import Graph, Insight
from common.monitoring import get_logger

log = get_logger("learn.capture")

Distiller = Callable[[list[LessonSignal]], list[LessonSignal]]


def _key(statement: str) -> str:
    return hashlib.sha1(statement.strip().lower().encode()).hexdigest()[:10]


def _grounded(graph: Graph, refs: list[str]) -> bool:
    return not graph.nodes or any(r in graph.nodes for r in refs)


def _to_insight(sig: LessonSignal, *, context_id: str, run_id: str, step: str, now: str) -> Insight:
    return Insight(
        id=f"insight:{context_id}:{sig.kind}-{_key(sig.statement)}",
        kind=sig.kind, context_id=context_id, question_id="",
        statement=sig.statement.strip(), answered_by="agent-self", confidence=sig.confidence,
        source_refs=list(sig.source_refs), created_at=now, run_id=run_id, rationale=sig.rationale,
        origin_step=step, scope="context", status="active",
    )


def capture_lessons(
    bank, *, context_id: str, run_id: str = "", step: str = "",
    signals: list[LessonSignal], distiller: Distiller | None = None, now: str = "",
) -> list[Insight]:
    """Distil `signals` → grounded, deduped Insight lessons; persist + index. Returns those written"""
    try:
        if distiller is not None:
            signals = distiller(signals) or []
        graph, _ = bank.load_index()
        kept: list[Insight] = []
        seen: set[str] = set()
        for sig in signals:
            if not sig.statement.strip() or not _grounded(graph, sig.source_refs):
                continue
            ins = _to_insight(sig, context_id=context_id, run_id=run_id, step=step, now=now)
            if ins.id in seen or bank.read_insight(ins.id) is not None:
                continue
            seen.add(ins.id)
            bank.upsert_insight(ins)
            kept.append(ins)
        if kept:
            bank.update_index(lambda g: [g.add_insight(i) for i in kept])
        log.info("learn: captured %d lesson(s) step=%s ctx=%s", len(kept), step, context_id)
        return kept
    except Exception as exc:  # noqa: BLE001 — best-effort; must not break the pipeline
        log.warning("learn: capture failed (%s); skipped", exc)
        return []
