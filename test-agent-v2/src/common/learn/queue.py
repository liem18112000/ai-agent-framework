"""Durable capture queue (L1): enqueue lesson-capture jobs, drain them OFF the request path."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from common.learn.capture import Distiller, capture_lessons
from common.learn.model import LessonSignal
from common.memory.bank import ROOT
from common.monitoring import get_logger

log = get_logger("learn.queue")
QUEUE_PATH = f"{ROOT}/learn/capture-queue.json"


@dataclass
class CaptureJob:
    """A queued capture unit: context/step + serialized signals to distil."""

    id: str
    context_id: str
    run_id: str = ""
    step: str = ""
    signals: list[dict] = field(default_factory=list)
    created_at: str = ""


def enqueue(bank, job: CaptureJob) -> None:
    """Append a job to the durable queue (CAS). O(1) — safe on the request path."""
    bank.mutate_json(QUEUE_PATH, lambda q: [*q, asdict(job)], default=[])


def drain(bank, *, distiller: Distiller | None = None, now: str = "", max_jobs: int = 50) -> int:
    """Run pending capture jobs off the request path; return how many processed. At-least-once: a"""
    pending = bank.get_json(QUEUE_PATH, []) or []
    done: list[str] = []
    for raw in pending[:max_jobs]:
        try:
            capture_lessons(
                bank, context_id=raw["context_id"], run_id=raw.get("run_id", ""),
                step=raw.get("step", ""), now=now, distiller=distiller,
                signals=[LessonSignal(**s) for s in raw.get("signals", [])],
            )
            done.append(raw["id"])
        except Exception as exc:  # noqa: BLE001 — one bad job must not block the drain
            log.warning("learn: job %s failed (%s); left for retry", raw.get("id"), exc)
    if done:
        ids = set(done)
        bank.mutate_json(QUEUE_PATH, lambda q: [j for j in q if j.get("id") not in ids], default=[])
    log.info("learn: drained %d job(s)", len(done))
    return len(done)
