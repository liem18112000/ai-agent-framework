"""TPD implement domain logic — framework-neutral (extracted from executor/implement.py in C2)."""

from __future__ import annotations

from dataclasses import asdict

from common import learn
from test_plan_definition.implement.generate import ImplementResult
from test_plan_definition.models import HAPPY, NEGATIVE
from test_plan_definition.monitoring import get_logger

log = get_logger("tpd.implement_ops")


def _capture_implement(bank, context_id: str, result: ImplementResult) -> None:
    if not learn.capture_enabled("TPD"):
        return
    try:
        sigs = learn.from_implement(result.scenarios, context_id=context_id)
        if sigs:
            learn.enqueue(bank, learn.CaptureJob(
                id=f"cap-implement-{context_id}", context_id=context_id, step="implement",
                signals=[asdict(s) for s in sigs]))
    except Exception as exc:  # noqa: BLE001 — capture must not break implement
        log.warning("implement: lesson capture skipped (%s)", exc)


def summarize_implement(result: ImplementResult) -> str:
    happy = sum(s.kind == HAPPY for s in result.scenarios)
    negative = sum(s.kind == NEGATIVE for s in result.scenarios)
    titles = "\n".join(f"- [{s.kind}] {s.title}" for s in result.scenarios)
    feature = "  Exported a BDD .feature.\n" if result.feature else ""
    return (
        f"Implement complete: {len(result.test_data)} test-data, {len(result.scenarios)} "
        f"scenarios ({happy} happy / {negative} negative), {len(result.steps)} steps.\n{feature}\n"
        f"{titles}"
    )
