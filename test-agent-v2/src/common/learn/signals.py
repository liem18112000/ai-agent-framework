"""Per-step signal collectors (L2/L3): step artifacts → candidate LessonSignals."""

from __future__ import annotations

from collections import Counter

from common.learn.model import LessonSignal
from common.models import CORRECTION, LESSON


def from_decisions(decisions) -> list[LessonSignal]:
    """Human-confirmed decisions (refine or define) → cited lesson signals; a choice that rejected"""
    return [
        LessonSignal(statement=stmt, kind=CORRECTION if getattr(d, "rejected", None) else LESSON,
                     source_refs=list(getattr(d, "source_refs", []) or []),
                     confidence=getattr(d, "confidence", "low"), rationale=getattr(d, "rationale", ""))
        for d in decisions
        if (stmt := getattr(d, "statement", "").strip()) and getattr(d, "answered_by", "") == "human"
    ]


def from_gather(repos: list[str], *, seed_ref: str) -> list[LessonSignal]:
    """Which repo implements the seed. `repos` are clean `<ws>/<repo>` slugs (built codegraphs);"""
    return [
        LessonSignal(statement=f"{seed_ref} is implemented in repo {r}", kind=LESSON,
                     source_refs=[seed_ref, f"codegraph:{r}"], confidence="medium")
        for r in repos if r
    ]


def from_implement(scenarios, *, context_id: str) -> list[LessonSignal]:
    """ONE bounded coverage-summary lesson per implement — never the scenarios themselves (those"""
    if not scenarios:
        return []
    kinds = sorted(Counter(getattr(s, "kind", "") for s in scenarios).items())
    summary = (f"Test plan for {context_id} implemented: {len(scenarios)} scenarios — "
               + ", ".join(f"{n} {k}" for k, n in kinds))
    refs = sorted({r for s in scenarios for r in getattr(s, "source_refs", [])})[:5]
    return [LessonSignal(statement=summary, kind=LESSON, source_refs=refs, confidence="low")]
