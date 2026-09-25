"""Per-step signal collectors (L2/L3): step artifacts → candidate LessonSignals."""

from __future__ import annotations

from collections import Counter

from common.learn.model import LessonSignal
from common.models import LESSON


def from_gather(repos: list[str], *, seed_ref: str) -> list[LessonSignal]:
    """Which repo implements the seed. `repos` are clean `<ws>/<repo>` slugs (built codegraphs);

    R6: every signal carries its WARRANT in `rationale` — openrig's rule that a promoted claim
    travels with the evidence that earned it ("canon without warrants is cargo cult with good
    formatting"). The warrant states HOW this position could know the claim, not that it is true."""
    return [
        LessonSignal(statement=f"{seed_ref} is implemented in repo {r}", kind=LESSON,
                     source_refs=[seed_ref, f"codegraph:{r}"], confidence="medium",
                     rationale=f"observed during gather: a codegraph was built for {r} while "
                               f"crawling {seed_ref}")
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
    return [LessonSignal(statement=summary, kind=LESSON, source_refs=refs, confidence="low",
                         rationale=f"counted from the {len(scenarios)} scenarios this implement "
                                   f"pass generated for {context_id}")]
