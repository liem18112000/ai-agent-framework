"""The grounded context pack a refine session reads: notes + link graph + gaps.

Pure data container. It is built (`common.interrogate.pack.load_pack`) from the Memory Bank the
gather loop wrote, or handed straight from a fresh crawl; `summary_text()` renders it
compactly for the LLM prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from common.models.graph import Graph, Note
from common.models.refine import INSIGHT


@dataclass
class Pack:
    context_id: str
    notes: list[Note] = field(default_factory=list)
    graph: Graph = field(default_factory=Graph)
    gaps: list[str] = field(default_factory=list)
    seed: str = ""
    lessons: list[str] = field(default_factory=list)  # L4: prior lessons recalled for this seed

    @property
    def grounded(self) -> list[Note]:
        """The gathered notes (everything that is not an already-recorded insight)."""
        return [n for n in self.notes if n.type != INSIGHT]

    @property
    def insights(self) -> list[Note]:
        return [n for n in self.notes if n.type == INSIGHT]

    def is_empty(self) -> bool:
        return not self.grounded

    def recorded_only_types(self) -> list[str]:
        """Distinct link types that were recorded but not followed (out-of-scope)."""
        seen: dict[str, None] = {}
        for n in self.grounded:
            for lr in n.links:
                if not lr.in_scope:
                    seen.setdefault(lr.type, None)
        return list(seen)

    def summary_text(self, limit: int = 6000) -> str:
        lines = [f"# Context pack {self.context_id}" + (f" (seed {self.seed})" if self.seed else "")]
        for n in self.grounded:
            lines.append(f"\n## {n.type}: {n.id} — {n.title}")
            if n.synopsis:
                lines.append(n.synopsis)
            followed = [lr for lr in n.links if lr.in_scope]
            recorded = [lr for lr in n.links if not lr.in_scope]
            if followed:
                lines.append("followed links: " + ", ".join(f"{lr.canonical_url}" for lr in followed))
            if recorded:
                lines.append("recorded-only: " + ", ".join(f"{lr.type}:{lr.url}" for lr in recorded))
        if self.gaps:
            lines.append("\n## Declared gaps (unreachable/broken)\n" + "\n".join(f"- {g}" for g in self.gaps))
        if self.insights:
            lines.append("\n## Already decided (existing insights)")
            lines += [f"- {n.title}" for n in self.insights]
        if self.lessons:
            lines.append("\n## Prior lessons (from earlier runs — don't re-learn these)")
            lines += [f"- {lesson}" for lesson in self.lessons]
        return "\n".join(lines)[:limit]
