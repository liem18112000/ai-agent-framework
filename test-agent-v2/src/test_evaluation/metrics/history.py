"""E4 trend history — append each nightly run to an append-only JSONL for PQS-over-time trending."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from test_evaluation.models import HistoryRecord


def append_run(path: str | Path, *, timestamp: str, commit: str, pqs: float,
               components: dict, per_seed: dict) -> HistoryRecord:
    """Append one run record and return it. `path` is a JSONL file (created if absent)."""
    record = HistoryRecord(timestamp=timestamp, commit=commit, pqs=pqs, components=components, per_seed=per_seed)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(record)) + "\n")
    return record


def load_history(path: str | Path) -> list[HistoryRecord]:
    p = Path(path)
    if not p.exists():
        return []
    return [HistoryRecord.from_dict(json.loads(line))
            for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def regressed(current_pqs: float, baseline_pqs: float, band: float = 0.05) -> bool:
    """True when PQS dropped more than `band` below baseline — the main-branch alert condition."""
    return (baseline_pqs - current_pqs) > band
