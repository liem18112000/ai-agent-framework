"""Crawl result container — the notes, link inventory, gaps, and run-log one crawl produces."""

from __future__ import annotations

from dataclasses import dataclass, field

from common.models import LinkRecord, Note, RunLog


@dataclass
class CrawlResult:
    notes: list[Note] = field(default_factory=list)
    inventory: list[LinkRecord] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    run: RunLog | None = None
