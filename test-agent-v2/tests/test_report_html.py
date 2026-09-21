"""The QA/QC report renders the 10 canonical sections + BDD flow, downloads and TEV rubric from the run."""
from __future__ import annotations

from common.benchmark.model import Benchmark
from common.benchmark.store import write_benchmark
from common.memory import MemoryBank
from common.models import Answer, Question
from common.store import build_object_store
from common.testplan import memory as store
from common.testplan.models import PlanDecision, TestData, TestPlan, TestScenario, TestStep
from common.testplan.report import build_report_html

# the 10 canonical QA/QC sections, keyed by their stable anchor ids (labels carry &amp; escaping)
_SECTION_IDS = ("s-summary", "s-arch", "s-decisions", "s-method", "s-scenarios",
                "s-coverage", "s-gaps", "s-oos", "s-bench", "s-deliver")


def _bank(monkeypatch) -> MemoryBank:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    return MemoryBank(build_object_store())


def test_report_renders_ten_qa_sections_with_bdd_downloads_and_tev(monkeypatch):
    monkeypatch.setenv("ATLASSIAN_BASE_URL", "https://example.atlassian.net")
    bank = _bank(monkeypatch)
    ctx = "LUZ-158230"
    store.write_plan(bank, TestPlan(
        id="plan:1", context_id=ctx, methodology=["api"], scope=["import a valid zip lands docs"],
        out_of_scope=["sender authorization"], metrics=["end-state"], test_design=["EP"],
        test_kinds=["happy", "security"], source_refs=["jira:LUZ-158230"], status="confirmed"))
    store.write_plan_brief(bank, ctx, "# System\nePost ZIP import.\n\n## Requirement\nImport lands docs.")
    store.write_decisions(bank, ctx, [
        PlanDecision(id="d1", kind="decision", context_id=ctx, question_id="q1", round="scope",
                     statement="Test the import job end-to-end", chosen="e2e", rationale="core path",
                     rejected=["unit only"], source_refs=["jira:LUZ-158230"])])
    store.write_test_data(bank, ctx, [
        TestData(id=f"td:{ctx}:valid", kind="fixture", plan_id="plan:1", spec={"file": "transfer.zip"})])
    store.write_scenarios(bank, ctx, [
        TestScenario(id=f"scenario:{ctx}:a:happy", plan_id="plan:1", title="Valid import lands",
                     kind="happy", description="imports a valid transfer.zip", rationale="core path",
                     data_refs=[f"td:{ctx}:valid"]),
        TestScenario(id=f"scenario:{ctx}:b:security", plan_id="plan:1", title="Zip-slip blocked",
                     kind="security", description="path traversal is rejected", rationale="security surface"),
    ])
    store.write_steps(bank, ctx, [
        TestStep(id="s1", scenario_id=f"scenario:{ctx}:a:happy", order=1, keyword="Given",
                 action="a valid transfer.zip", data_refs=[f"td:{ctx}:valid"]),
        TestStep(id="s2", scenario_id=f"scenario:{ctx}:a:happy", order=2, keyword="When",
                 action="the import job completes"),
        TestStep(id="s3", scenario_id=f"scenario:{ctx}:a:happy", order=3, keyword="Then",
                 action="assert documents landed", expected="documents exist in the recipient eArchive"),
    ])
    # an unanswered question -> a dev-confirmation item in §7
    store.write_questions(bank, ctx, [Question(id="q9", round="scope", question="Which tenant is canonical?",
                                               why="affects fixtures", status="open")])
    store.write_answers(bank, ctx, [Answer(question_id="q1", text="e2e")])
    write_benchmark(bank, Benchmark(
        context_id=ctx, ok=True, pqs=0.81, tps=0.66,
        pqs_components={"faithfulness": 0.9, "ctx_precision": 0.8, "ctx_recall": 0.7,
                        "relevancy": 0.85, "trajectory": 0.75},
        tps_components={"fault_detection": 0.6, "brief_groundedness": 0.8, "coverage": 0.5,
                        "oracle_strength": 0.7, "trajectory": 0.7},
        retrieval={"precision": 0.8, "recall": 1.0, "leaked": []}))

    html = build_report_html(bank, ctx)

    for sid in _SECTION_IDS:                                           # all 10 QA/QC sections present
        assert f'id="{sid}"' in html, f"missing section: {sid}"
    assert "Valid import lands" in html and "Zip-slip blocked" in html          # scenarios rendered
    assert "documents exist in the recipient eArchive" in html                  # oracle/expected surfaced
    assert "fl-step" in html and "the import job completes" in html             # detailed step flow
    assert 'class="mermaid"' in html and "flowchart" in html                    # §2/§7/§8 diagrams
    assert "https://example.atlassian.net/browse/LUZ-158230" in html           # clickable ticket link
    assert 'download="' in html and "data:application/json" in html            # downloadable test data
    assert "Which tenant is canonical?" in html                                 # §7 dev-confirmation item
    assert "PQS &mdash; pack quality" in html or ">0.81<" in html               # §9 PQS score
    assert "Faithfulness" in html and "Fault detection" in html                 # §9 component rubric
    assert "Scores from the Test-Evaluation agent" in html                      # §9 required preamble
    assert "{" not in html.split("<style>")[0]                                  # header fully formatted


def test_report_survives_empty_run(monkeypatch):
    bank = _bank(monkeypatch)
    html = build_report_html(bank, "run-empty")   # nothing persisted
    assert "No scenarios generated" in html
    for sid in _SECTION_IDS:                       # skeleton still shows every section
        assert f'id="{sid}"' in html
    assert "Scores from the Test-Evaluation agent" in html   # §9 rubric renders even unscored


def test_gherkin_emits_then_for_oracle_on_a_keyword_step():
    """TPL-01: the oracle in `expected` must reach the .feature even when the step already carries a
    keyword (When/Given) and there is no separate Then step — else the executable Gherkin is oracle-less."""
    from common.testplan.report.html import _gherkin_one

    sc = TestScenario(id="s1", plan_id="p", title="Do X")
    sts = [TestStep(id="s1#s1", scenario_id="s1", order=1, keyword="When",
                    action="the import job completes", expected="documents exist in the eArchive")]
    out = _gherkin_one(sc, sts)
    assert "When the import job completes" in out
    assert "Then documents exist in the eArchive" in out


def test_report_title_is_the_covered_ticket_not_first_source_ref(monkeypatch):
    """Regression: the title must name the ticket the scenarios cover, not the first Jira key in
    plan/decision source_refs — which can be an out-of-scope reference (e.g. LUZ-158243 here)."""
    bank = _bank(monkeypatch)
    ctx = "run-title"
    # plan.source_refs lists the out-of-scope key FIRST, the real one second
    store.write_plan(bank, TestPlan(
        id="plan:1", context_id=ctx, methodology=["api"], status="confirmed",
        source_refs=["jira:LUZ-158243", "jira:LUZ-158230"]))
    store.write_scenarios(bank, ctx, [
        TestScenario(id=f"scenario:{ctx}:1", plan_id="plan:1", title="Import lands",
                     source_refs=["jira:LUZ-158230"]),
        TestScenario(id=f"scenario:{ctx}:2", plan_id="plan:1", title="Metadata maps",
                     source_refs=["jira:LUZ-158230"]),
    ])
    html = build_report_html(bank, ctx)
    assert "Test plan &mdash; LUZ-158230" in html
    assert "&mdash; LUZ-158243" not in html


def test_plan_preview_renders_plan_stage_only_and_titles_by_subject_ticket(monkeypatch):
    """The dedicated plan preview (before approve_plan): plan-stage sections only (no scenarios),
    titled by the run's SUBJECT ticket (the pack's grounded Jira node) — NOT the out-of-scope key that
    dominates the plan/decision source_refs."""
    from common.models.graph import JIRA_ISSUE, Note
    from common.report.plan_preview import build_plan_preview_html

    bank = _bank(monkeypatch)
    ctx = "run-planprev"
    # the gathered subject ticket (what the plan is about)
    subject = Note(id="jira:LUZ-158230", type=JIRA_ISSUE, title="ZIP import of health docs", run_id=ctx,
                   source_url="https://example.atlassian.net/browse/LUZ-158230", synopsis="ticket under test")
    bank.upsert_note(subject)
    bank.update_index(lambda g: g.add_note(subject))
    store.write_plan(bank, TestPlan(
        id="plan:1", context_id=ctx, methodology=["api"], scope=["import a valid zip lands docs"],
        out_of_scope=["sender authorization"], metrics=["end-state"], test_design=["EP"],
        test_kinds=["happy"], status="confirmed",
        source_refs=["jira:LUZ-158243", "jira:LUZ-158230"]))  # out-of-scope key listed FIRST
    store.write_plan_brief(bank, ctx, "# System\nePost ZIP import.\n\n## Requirement\nImport lands docs.")
    store.write_decisions(bank, ctx, [
        PlanDecision(id="d1", kind="decision", context_id=ctx, question_id="q1", round="scope",
                     statement="Test the import job end-to-end", chosen="e2e", rationale="core path",
                     rejected=["unit only"], source_refs=["jira:LUZ-158230"]),
        PlanDecision(id="d2", kind="decision", context_id=ctx, question_id="q2", round="methodology",
                     statement="API-weighted", chosen="api", source_refs=["jira:LUZ-158230"])])
    store.write_questions(bank, ctx, [
        Question(id="q1", round="scope", question="answered", status=""),
        Question(id="q9", round="scope", question="Which tenant is canonical?",
                 why="affects fixtures", status="open")])
    store.write_answers(bank, ctx, [Answer(question_id="q1", text="e2e")])

    html = build_plan_preview_html(bank, ctx)

    assert "Plan preview &mdash; LUZ-158230" in html          # dominant ticket, NOT LUZ-158243
    assert "&mdash; LUZ-158243" not in html
    assert 'id="p-summary"' in html and 'id="p-decisions"' in html and 'id="p-open"' in html
    assert "Test the import job end-to-end" in html          # decision surfaced
    assert "sender authorization" in html                    # out-of-scope surfaced
    assert "Which tenant is canonical?" in html              # open question surfaced
    assert "<details" in html                                # decisions are collapsible (scannable)
    assert 'id="s-scenarios"' not in html                    # NO scenarios at the plan stage
