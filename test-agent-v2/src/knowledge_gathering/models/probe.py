"""Pre-crawl seed-probe model — the best-effort seed fetch shared by the G0/G1/G2 phases."""

from __future__ import annotations

from typing import NamedTuple


class SeedProbe(NamedTuple):
    """One best-effort seed fetch shared by the pre-crawl G0/G1/G2 phases (defaults = neutral)."""

    terms: str = ""
    thin: bool = False
    project: str | None = None
    title: str = ""
    description: str = ""
    labels: list[str] | None = None
    parent: str | None = None
