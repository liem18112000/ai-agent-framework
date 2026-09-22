"""Codegraph: URL/seed routing, graphify-output parsing, GCS store, and fetcher registration."""

from __future__ import annotations

from common.codegraph.distill import distill_code_note
from common.codegraph.runner import CodeGraphResult, parse_report, scan_api_surface
from common.codegraph.store import store_code_graph
from common.extract import classify_url
from common.memory.bank import MemoryBank
from common.models import CODEGRAPH
from knowledge_gathering.gather.crawl.crawl import _fetchable
from knowledge_gathering.gather.crawl.fetch import (  # noqa: F401 — triggers registration
    NodeFetcher,
    fetch_node,
)
from knowledge_gathering.gather.seed import normalize_seed

REPORT = """# Graph Report - luz_docs_import

## Corpus Check
- 61 files · ~24,288 words

## Summary
- 470 nodes · 983 edges · 20 communities

## God Nodes (most connected - your core abstractions)
1. `DocsImportAsyncService` - 43 edges
2. `ImportJob` - 36 edges
"""

GRAPH = {
    "nodes": [
        {"id": "1", "label": "ImportJobResource",
         "source_file": "src/main/java/ch/klara/luz/docsimport/rest/ImportJobResource.java",
         "metadata": {"kind": "class"}},
        {"id": "2", "label": "AntivirusRestClient",
         "source_file": "src/main/java/ch/klara/luz/docsimport/rest/client/AntivirusRestClient.java",
         "metadata": {"kind": "interface"}},
        {"id": "3", "label": "UPLOADED",
         "source_file": "src/main/java/ch/klara/luz/docsimport/enums/JobStatus.java",
         "metadata": {"kind": "enum_constant"}},
        {"id": "4", "label": "SCANNING",
         "source_file": "src/main/java/ch/klara/luz/docsimport/enums/JobStatus.java",
         "metadata": {"kind": "enum_constant"}},
        {"id": "5", "label": "JobStatus",
         "source_file": "src/main/java/ch/klara/luz/docsimport/enums/JobStatus.java",
         "metadata": {"kind": "file"}},
    ],
    "edges": [],
}


def test_classify_repo_url_is_codegraph():
    assert classify_url("https://bitbucket.org/axonivy-prod/luz_docs_import") == (
        CODEGRAPH, "codegraph:axonivy-prod/luz_docs_import")
    t, cid = classify_url("https://bitbucket.org/axonivy-prod/luz_docs_import/src/master/pom.xml")
    assert t == "bitbucket" and cid == "bitbucket:axonivy-prod/luz_docs_import/src/master/pom.xml"
    t2, _ = classify_url("https://bitbucket.org/axonivy-prod/luz_docs_import/pull-requests/42")
    assert t2 == "bitbucket"


def test_seed_repo_shorthand():
    assert normalize_seed("axonivy-prod/luz_docs_import") == "codegraph:axonivy-prod/luz_docs_import"
    assert normalize_seed("LUZ-158390") == "jira:LUZ-158390"


def test_parse_report():
    p = parse_report(REPORT)
    assert p["counts"] == {"nodes": 470, "edges": 983, "communities": 20, "files": 61}
    assert p["god_nodes"][0] == {"name": "DocsImportAsyncService", "edges": 43}


def test_scan_api_surface():
    api = scan_api_surface(GRAPH)
    assert api["endpoints"] == ["src/main/java/ch/klara/luz/docsimport/rest/ImportJobResource.java"]
    assert api["rest_clients"] == ["src/main/java/ch/klara/luz/docsimport/rest/client/AntivirusRestClient.java"]
    enum_members = api["enums"]["src/main/java/ch/klara/luz/docsimport/enums/JobStatus.java"]
    assert enum_members == ["SCANNING", "UPLOADED"]


def _sample_result() -> CodeGraphResult:
    return CodeGraphResult(
        repo="luz_docs_import", commit="bf0d26f", built_at="2026-09-01T00:00:00Z", tool="graphify 0.9.27",
        files=61, nodes=470, edges=983, communities=20,
        god_nodes=[{"name": "ImportJob", "edges": 36}],
        endpoints=["a/ImportJobResource.java"], rest_clients=["a/AntivirusRestClient.java"],
        enums={"a/JobStatus.java": ["DONE", "FAILED", "SCANNING", "UPLOADED"]},
        report_md=REPORT, graph_json=GRAPH,
    )


def test_store_and_read_versioned(fake_bucket):
    bank = MemoryBank(fake_bucket)
    meta = store_code_graph(bank, _sample_result())
    assert "graph_json" not in meta and "report_md" not in meta
    assert "memory/graphify/luz_docs_import/bf0d26f/graph.json" in fake_bucket.store
    assert "memory/graphify/luz_docs_import/latest/GRAPH_REPORT.md" in fake_bucket.store


def test_distill_note_front_loads_api():
    md = distill_code_note(_sample_result())
    assert "ImportJobResource.java" in md and "JobStatus.java" in md and "UPLOADED" in md
    assert "ImportJob (36)" in md


def test_codegraph_fetcher_registered():
    from common.models import Scope

    assert "codegraph" in NodeFetcher.registry
    assert _fetchable("codegraph:axonivy-prod/luz_docs_import", Scope())


async def test_crawl_builds_codegraph_note(monkeypatch, fake_bucket):
    """Full flow through the real crawl(): a repo seed → CodeGraphFetcher → distilled note persisted."""
    from knowledge_gathering.gather.crawl import crawl as crawl_fn
    from knowledge_gathering.gather.crawl.fetch import codegraph as cg_mod

    bank = MemoryBank(fake_bucket)
    monkeypatch.setattr(cg_mod, "build_bank", lambda: bank)
    monkeypatch.setattr(cg_mod, "build_and_store", lambda b, ws, repo, **k: _sample_result())

    result = await crawl_fn(
        client=None, bank=bank, seed="axonivy-prod/luz_docs_import",
        depth=0, max_seconds=30, distiller=lambda note, text: text,
    )
    assert [n.type for n in result.notes] == [CODEGRAPH]
    note = result.notes[0]
    assert note.id == "codegraph:axonivy-prod/luz_docs_import"
    assert "ImportJobResource" in note.synopsis
    assert bank.read_note(note.id, CODEGRAPH) is not None
