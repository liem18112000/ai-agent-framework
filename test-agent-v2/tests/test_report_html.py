"""The enriched HTML report renders the 5 tabs + a per-test-case flow from persisted run data."""
from __future__ import annotations

from common.memory import MemoryBank
from common.store import build_object_store
from common.testplan import memory as store
from common.testplan.models import TestPlan, TestScenario, TestStep
from common.testplan.report import build_report_html


def _bank(monkeypatch) -> MemoryBank:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    return MemoryBank(build_object_store())


def test_report_has_five_tabs_scenarios_and_case_flow(monkeypatch):
    bank = _bank(monkeypatch)
    ctx = "run-report-test"
    store.write_plan(bank, TestPlan(
        id="plan:1", context_id=ctx, methodology=["api"], scope=["import a valid zip lands docs"],
        out_of_scope=["sender authorization"], metrics=["end-state"], test_design=["EP"],
        test_kinds=["happy", "security"], status="confirmed"))
    store.write_scenarios(bank, ctx, [
        TestScenario(id=f"scenario:{ctx}:a:happy", plan_id="plan:1", title="Valid import lands",
                     kind="happy", description="imports a valid transfer.zip", rationale="core path"),
        TestScenario(id=f"scenario:{ctx}:b:security", plan_id="plan:1", title="Zip-slip blocked",
                     kind="security", description="path traversal is rejected", rationale="security surface"),
    ])
    store.write_steps(bank, ctx, [
        TestStep(id="s1", scenario_id=f"scenario:{ctx}:a:happy", order=1, keyword="Given",
                 action="a valid transfer.zip"),
        TestStep(id="s2", scenario_id=f"scenario:{ctx}:a:happy", order=2, keyword="When",
                 action="the import job completes"),
        TestStep(id="s3", scenario_id=f"scenario:{ctx}:a:happy", order=3, keyword="Then",
                 action="assert documents landed", expected="documents exist in the recipient eArchive"),
    ])

    html = build_report_html(bank, ctx)

    for label in ("Scenarios", "Feature files", "Test data", "Benchmark", "Test-case workflow"):
        assert label in html, f"missing tab: {label}"
    assert "Valid import lands" in html and "Zip-slip blocked" in html          # scenarios rendered
    assert "documents exist in the recipient eArchive" in html                  # oracle/expected surfaced
    assert "fl-step" in html and "the import job completes" in html             # per-case flow rendered
    assert "Feature:" in html                                                   # gherkin generated
    assert "{css}" not in html and "{workflow}" not in html                     # template fully formatted


def test_report_survives_empty_run(monkeypatch):
    bank = _bank(monkeypatch)
    html = build_report_html(bank, "run-empty")   # nothing persisted
    assert "No scenarios" in html and "Test-case workflow" in html
