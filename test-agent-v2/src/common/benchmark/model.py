"""Benchmark — a run's frozen TEV scores (PQS/TPS + highlights), cached as one JSON blob.

The model + blob I/O live in `common` (any agent may read them); the *compute* (which calls the
scoring engines) lives in `test_evaluation.benchmark`, since `common` must not import an agent.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

# Bump to invalidate every cached blob at once (read_benchmark treats an older version as a miss).
SCHEMA_VERSION = 1


@dataclass
class Benchmark:
    """One run's scorecard. `ok=false` (with `error`) is a first-class record — a run that failed or
    had nothing to score still gets a Benchmark so `even failed` runs show up in compare/summarize."""

    context_id: str
    ok: bool = False
    pqs: float | None = None            # None = no pack to score
    tps: float | None = None            # None = no plan to score
    pqs_components: dict = field(default_factory=dict)
    tps_components: dict = field(default_factory=dict)
    retrieval: dict | None = None       # {"precision", "recall", "leaked"} highlight from the pack eval
    seed: str = ""
    computed_at: str = ""               # ISO-ish UTC stamp
    error: str = ""                     # set when ok=false
    schema_version: int = SCHEMA_VERSION

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Benchmark:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})
