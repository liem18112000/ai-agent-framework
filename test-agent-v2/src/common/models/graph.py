"""Knowledge-graph data contracts — links, scope, notes, run-logs, and the index.

The gather side of the shared model: a `LinkRecord` edge, the `Scope` that decides what
to follow, a distilled `Note`, the `RunLog` for one crawl, and the `Graph` index that
stitches notes (and refine insights) into nodes + edges.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from common.models.refine import INSIGHT

if TYPE_CHECKING:
    from common.models.refine import Insight

# Link types.
JIRA_ISSUE = "jira-issue"
CONFLUENCE_PAGE = "confluence-page"
BITBUCKET = "bitbucket"
FIGMA = "figma"
GOOGLE_DOC = "google-doc"
ATTACHMENT = "attachment"
EXTERNAL_WEB = "external-web"
CODEGRAPH = "codegraph"  # a whole Bitbucket repo, distilled by graphify into a code graph


@dataclass
class LinkRecord:
    """One edge in the knowledge graph — a link found on a node."""

    source_id: str
    url: str
    type: str
    origin: str  # description | comment | remotelink | issuelink | body-storage | child | attachment | regex
    anchor_text: str = ""
    canonical_url: str = ""
    in_scope: bool = False
    followed: bool = False
    http_status: int | None = None
    discovered_at: str = ""


@dataclass(frozen=True)
class Scope:
    """What counts as *follow* (pushed to the frontier) vs *record-only*."""

    follow_types: tuple[str, ...] = (JIRA_ISSUE, CONFLUENCE_PAGE)
    follow_web: bool = False  # G3: promote already-linked external-web URLs from recorded → fetchable
    max_web: int = 8  # G3 sub-budget: cap external-web GETs one link-heavy ticket can spawn

    def follows(self, typ: str) -> bool:
        """True if a link of ``typ`` should be pushed to the frontier (vs recorded-only).

        external-web is followable ONLY when web-following is explicitly enabled — default OFF
        keeps external-web recorded-not-fetched, byte-for-byte as before.
        """
        return typ in self.follow_types or (typ == EXTERNAL_WEB and self.follow_web)


@dataclass
class Note:
    """A distilled memory note for one node (persisted as md + json sidecar)."""

    id: str  # canonical id, e.g. "jira:LUZ-158390"
    type: str
    source_url: str = ""
    title: str = ""
    fetched_at: str = ""
    depth: int = 0
    run_id: str = ""
    confidence: str = "high"
    synopsis: str = ""
    links: list[LinkRecord] = field(default_factory=list)
    backlinks: list[str] = field(default_factory=list)


@dataclass
class RunLog:
    """One run-log entry: inputs, sources, output, confidence."""

    run_id: str
    seed: str
    params: dict = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    nodes_fetched: int = 0
    links_found: int = 0
    gaps: list[str] = field(default_factory=list)
    confidence: str = ""
    started: str = ""
    ended: str = ""


@dataclass
class Graph:
    """The knowledge index — nodes + edges, keyed for cheap merge."""

    nodes: dict[str, dict] = field(default_factory=dict)  # id -> {id, type, title}
    edges: dict[str, dict] = field(default_factory=dict)  # "src->target" -> edge

    def add_note(self, note: Note) -> None:
        self.nodes[note.id] = {"id": note.id, "type": note.type, "title": note.title}
        for lr in note.links:
            key = f"{lr.source_id}->{lr.canonical_url}"
            self.edges[key] = {
                "source_id": lr.source_id,
                "target": lr.canonical_url,
                "type": lr.type,
                "origin": lr.origin,
                "in_scope": lr.in_scope,
            }

    def add_insight(self, insight: Insight) -> None:
        """Add an insight as a graph node, with an edge to each source it builds on."""
        self.nodes[insight.id] = {
            "id": insight.id,
            "type": INSIGHT,
            "title": insight.statement[:80],
        }
        for ref in insight.source_refs:
            key = f"{insight.id}->{ref}"
            self.edges[key] = {
                "source_id": insight.id,
                "target": ref,
                "type": INSIGHT,
                "origin": insight.kind,
                "in_scope": True,
            }

    def to_json(self) -> dict:
        return {"nodes": list(self.nodes.values()), "edges": list(self.edges.values())}

    @classmethod
    def from_json(cls, data: dict) -> Graph:
        g = cls()
        for n in data.get("nodes", []):
            g.nodes[n["id"]] = n
        for e in data.get("edges", []):
            g.edges[f"{e['source_id']}->{e['target']}"] = e
        return g
