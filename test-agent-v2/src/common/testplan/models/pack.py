"""PlanPack — the input the define/implement stages read."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from common.models import Pack


@dataclass
class PlanPack:
    pack: Pack
    understanding: str = ""

    @property
    def context_id(self) -> str:
        return self.pack.context_id

    def is_empty(self) -> bool:
        """Empty when there is nothing to plan against (no grounded notes, no insights)."""
        return self.pack.is_empty() and not self.pack.insights

    def summary_text(self, limit: int = 6000) -> str:
        """Compact rendering for an LLM prompt: the confirmed understanding, then the pack."""
        head = f"# Confirmed understanding\n{self.understanding}\n\n" if self.understanding else ""
        return (head + self.pack.summary_text(limit=limit))[:limit]
