"""Run graphify over a source tree and parse its output into a CodeGraphResult.

graphify is a local, tree-sitter code-intelligence tool (PyPI ``graphifyy``, CLI ``graphify``):
``graphify update <dir> --force`` re-extracts the code graph with NO API key (only the optional
community-naming / doc pass would use an LLM, which we never enable). It writes
``<dir>/graphify-out/{graph.json,GRAPH_REPORT.md}``.

This module is pure + synchronous so a fetcher can offload it with ``asyncio.to_thread``. The
report (god-nodes, hubs, surprising connections) is graphify's own human-readable distillation;
we parse that plus a light scan of graph.json for the API surface (endpoints / enums / clients).
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

GRAPHIFY_BIN = "graphify"
_SUMMARY_RE = re.compile(r"(\d+)\s+nodes\s*[·.]\s*(\d+)\s+edges\s*[·.]\s*(\d+)\s+communities")
_FILES_RE = re.compile(r"^-\s*(\d+)\s+files", re.MULTILINE)
_GODNODE_RE = re.compile(r"^\s*\d+\.\s*`([^`]+)`\s*-\s*(\d+)\s+edges", re.MULTILINE)


@dataclass
class CodeGraphResult:
    """Structured code intelligence for one repo build."""

    repo: str
    commit: str
    built_at: str
    tool: str = ""
    files: int = 0
    nodes: int = 0
    edges: int = 0
    communities: int = 0
    god_nodes: list[dict] = field(default_factory=list)  # [{name, edges}]
    endpoints: list[str] = field(default_factory=list)  # REST resource/controller files
    rest_clients: list[str] = field(default_factory=list)  # outbound dependency clients
    enums: dict[str, list[str]] = field(default_factory=dict)  # enum file -> member labels
    report_md: str = ""
    graph_json: dict = field(default_factory=dict)  # the raw graphify graph (nodes+edges)

    def meta(self) -> dict:
        """The compact registry/meta row (no heavy graph_json / report_md)."""
        d = asdict(self)
        d.pop("graph_json", None)
        d.pop("report_md", None)
        return d


def run_graphify(source_dir: Path, *, graphify_bin: str = GRAPHIFY_BIN, timeout: float = 300.0) -> Path:
    """Build/refresh the graph in ``source_dir`` and return the graphify-out dir.

    Raises CalledProcessError / TimeoutExpired / FileNotFoundError on failure, and
    RuntimeError if graphify finished but produced no graph.json.
    """
    subprocess.run(
        [graphify_bin, "update", str(source_dir), "--force"],
        check=True, capture_output=True, text=True, timeout=timeout,
    )
    out = source_dir / "graphify-out"
    if not (out / "graph.json").exists():
        raise RuntimeError("graphify finished but graph.json is missing")
    return out


def parse_report(md: str) -> dict:
    """Pull counts + god-nodes out of GRAPH_REPORT.md."""
    counts = {"nodes": 0, "edges": 0, "communities": 0, "files": 0}
    if m := _SUMMARY_RE.search(md):
        counts.update(nodes=int(m[1]), edges=int(m[2]), communities=int(m[3]))
    if m := _FILES_RE.search(md):
        counts["files"] = int(m[1])
    god = [{"name": n, "edges": int(e)} for n, e in _GODNODE_RE.findall(md)]
    return {"counts": counts, "god_nodes": god}


def scan_api_surface(graph: dict) -> dict:
    """Heuristic API surface from graph.json node source-files (Java-aware, language-agnostic).

    endpoints = REST resources/controllers; rest_clients = outbound dependency clients;
    enums = enum files -> their member symbol labels. Non-matching repos just yield empties.
    """
    endpoints: set[str] = set()
    rest_clients: set[str] = set()
    enums: dict[str, set[str]] = {}
    for n in graph.get("nodes", []):
        sf = (n.get("source_file") or "").replace("\\", "/")
        if not sf:
            continue
        low = sf.lower()
        base = sf.rsplit("/", 1)[-1]
        if "/rest/client/" in low or base.endswith(("RestClient.java", "Client.java")):
            rest_clients.add(sf)
        elif base.endswith(("Resource.java", "Controller.java", "Endpoint.java")) or "/resource/" in low:
            endpoints.add(sf)
        if "/enum/" in low or "/enums/" in low:
            label = n.get("label", "")
            kind = (n.get("metadata") or {}).get("kind", "")
            if label and kind not in ("file", ""):
                enums.setdefault(sf, set()).add(label)
    return {
        "endpoints": sorted(endpoints),
        "rest_clients": sorted(rest_clients),
        "enums": {k: sorted(v) for k, v in sorted(enums.items())},
    }


def build_code_graph(
    source_dir: Path, repo: str, commit: str, built_at: str,
    *, tool: str = "", graphify_bin: str = GRAPHIFY_BIN, timeout: float = 300.0,
) -> CodeGraphResult:
    """Run graphify on ``source_dir`` and distill its output into a CodeGraphResult."""
    out = run_graphify(source_dir, graphify_bin=graphify_bin, timeout=timeout)
    graph = json.loads((out / "graph.json").read_text(encoding="utf-8"))
    report = (out / "GRAPH_REPORT.md").read_text(encoding="utf-8") if (out / "GRAPH_REPORT.md").exists() else ""
    parsed = parse_report(report)
    api = scan_api_surface(graph)
    c = parsed["counts"]
    return CodeGraphResult(
        repo=repo, commit=commit, built_at=built_at, tool=tool,
        # graph.json is NetworkX node-link JSON: edges are under "links", not "edges".
        files=c["files"], nodes=c["nodes"] or len(graph.get("nodes", [])),
        edges=c["edges"] or len(graph.get("links", [])), communities=c["communities"],
        god_nodes=parsed["god_nodes"], endpoints=api["endpoints"],
        rest_clients=api["rest_clients"], enums=api["enums"],
        report_md=report, graph_json=graph,
    )
