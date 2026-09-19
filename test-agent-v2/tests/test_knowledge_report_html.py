"""The knowledge-preview report renders the 6 sections + map/concepts/gaps/sources/PQS from the pack."""
from __future__ import annotations

from common.benchmark.model import Benchmark
from common.benchmark.store import write_benchmark
from common.memory import MemoryBank
from common.models import Question
from common.models.graph import BITBUCKET, CONFLUENCE_PAGE, JIRA_ISSUE, LinkRecord, Note
from common.report.knowledge import build_knowledge_report_html
from common.store import build_object_store

# the 6 canonical sections, keyed by stable anchor id (labels carry &amp; escaping)
_SECTION_IDS = ("k-understanding", "k-map", "k-concepts", "k-gaps", "k-sources", "k-quality")


def _bank(monkeypatch) -> MemoryBank:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    return MemoryBank(build_object_store())


def _seed_note(bank, note: Note) -> None:
    bank.upsert_note(note)
    bank.update_index(lambda g: g.add_note(note))


def test_knowledge_report_renders_six_sections_map_gaps_sources_pqs(monkeypatch):
    monkeypatch.setenv("ATLASSIAN_BASE_URL", "https://example.atlassian.net")
    bank = _bank(monkeypatch)
    ctx = "LUZ-158230"
    bank.write_understanding(ctx, "# Understanding\nePost ZIP import lands health documents in the recipient eArchive.")
    for n in (
        Note(id="jira:LUZ-158230", type=JIRA_ISSUE, title="ZIP import of health docs", run_id=ctx,
             source_url="https://example.atlassian.net/browse/LUZ-158230",
             synopsis="The ticket under test: import a transfer.zip.",
             links=[LinkRecord(source_id="jira:LUZ-158230", url="https://x/spec", type=CONFLUENCE_PAGE,
                               origin="jira", canonical_url="https://x/spec", in_scope=True, anchor_text="import spec")]),
        Note(id="confluence:spec", type=CONFLUENCE_PAGE, title="Import spec", run_id=ctx,
             source_url="https://example.atlassian.net/wiki/spec",
             synopsis="Defines the transfer.zip format and dedup by content hash."),
        Note(id="code:importer", type=BITBUCKET, title="luz_docs_import service", run_id=ctx,
             source_url="https://bitbucket.org/x/luz_docs_import",
             synopsis="Implements the upload-zip endpoint and job."),
    ):
        _seed_note(bank, n)
    bank.write_questions(ctx, [Question(id="q1", round="scope", question="Which tenant is canonical for the fixture?",
                                        why="affects seeded data", status="open", recommendation="use the canary tenant")])
    write_benchmark(bank, Benchmark(
        context_id=ctx, ok=True, pqs=0.78,
        pqs_components={"faithfulness": 0.9, "ctx_precision": 0.7, "ctx_recall": 0.6,
                        "relevancy": 0.85, "trajectory": 0.8},
        retrieval={"precision": 0.7, "recall": 1.0, "leaked": []}))

    html = build_knowledge_report_html(bank, ctx)

    for sid in _SECTION_IDS:
        assert f'id="{sid}"' in html, f"missing section: {sid}"
    assert "lands health documents" in html                                      # §1 understanding
    assert 'class="mermaid"' in html and "flowchart" in html                     # §2/§3/§4 diagrams
    assert "https://example.atlassian.net/browse/LUZ-158230" in html            # clickable ticket
    assert "bitbucket.org/x/luz_docs_import" in html                            # §5 clickable source
    assert "Import spec" in html                                                 # §3/§5 a gathered concept
    assert "Which tenant is canonical for the fixture?" in html                  # §4 open question
    assert "Faithfulness" in html and ">0.78<" in html                          # §6 PQS + component rubric
    assert "Pack Quality Score" in html                                          # §6 preamble


def test_knowledge_report_survives_empty_run(monkeypatch):
    bank = _bank(monkeypatch)
    html = build_knowledge_report_html(bank, "run-empty")   # nothing gathered
    for sid in _SECTION_IDS:                                 # skeleton still shows every section
        assert f'id="{sid}"' in html
    assert "Nothing gathered yet" in html                    # §2 empty-map placeholder
    assert "Pack Quality Score" in html                      # §6 rubric renders even unscored
