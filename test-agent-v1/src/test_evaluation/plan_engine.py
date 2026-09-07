"""The plan-evaluation engine — score a persisted TestPlan + suite into a Test-Plan Score.

The downstream twin of engine.py (which scores the KGA pack). Reads the plan/brief/scenarios/
steps/test-data THIS context produced from the shared memory bank and scores four surfaces —
scope (id-overlap vs the golden in-scope set + the must_not_scope leak gate, reusing the same
node-overlap arithmetic), coverage adequacy (AC-recall + matrix completeness + traceability),
oracle strength + fault-class coverage (the fault-detection proxy), and brief groundedness
(fabrication rubrics) — combined into one TPS. Fully deterministic (no network, no LLM).

Independence: this NEVER imports test_plan_definition. It reads the TPD artifacts as plain JSON via
the bank's generic primitives at the documented path (memory/test-plan/<ctx>/…), and reads pack
behaviours via the shared common.interrogate.pack.load_pack — the same discipline engine.py uses.
The tier-trajectory component needs the tool sequence (only the offline harness has it), so at
runtime it is left neutral and scored there.
"""

from __future__ import annotations

from common.interrogate.pack import load_pack
from common.memory.bank import ROOT, _slug
from test_evaluation.metrics.coverage import coverage_scores
from test_evaluation.metrics.mutation import fault_class_coverage
from test_evaluation.metrics.node_overlap import retrieval_scores
from test_evaluation.metrics.oracle import oracle_strength
from test_evaluation.metrics.placeholders import placeholder_scan
from test_evaluation.metrics.rubrics import cites_only_real_ids, no_invented_urls
from test_evaluation.metrics.tps import tps
from test_evaluation.models import PlanEvalCase, PlanReport, RubricsReport, TPSComponents
from test_evaluation.monitoring import get_logger

log = get_logger("plan_engine")

_FULL_MATRIX = ["happy", "negative", "boundary", "error"]


def evaluate_plan(bank, context_id: str, case: PlanEvalCase | None = None,
                  *, trajectory: float = 1.0, detail: bool = False) -> PlanReport:
    """Score the plan+suite `context_id` produced. `case` supplies the golden ground truth
    (in-scope/must-not-scope ids, per-behaviour partitions + fault classes); without it, behaviours
    default to the pack's grounded notes with the full coverage matrix and scope has no ground truth."""
    d = f"{ROOT}/test-plan/{_slug(context_id)}"  # TPD artifact namespace (path contract; see module doc)
    plan = bank.get_json(f"{d}/plan.json", None) or {}
    brief = bank.get_text(f"{d}/plan-brief.md") or ""
    scenarios = bank.get_json(f"{d}/scenarios.json", [])
    steps = bank.get_json(f"{d}/steps.json", [])
    test_data = bank.get_json(f"{d}/test-data.json", [])
    pack = load_pack(bank, context_id)
    pack_ids = {n.id for n in pack.notes}

    # behaviours (ACs): the golden set if given, else the pack's grounded notes @ the full matrix
    behaviours = (case.behaviours if case and case.behaviours else
                  [{"id": n.id, "expected_partitions": list(_FULL_MATRIX)} for n in pack.grounded])

    # scope: reuse the node-overlap arithmetic (precision/recall/f1 + the must_not_scope leak gate)
    scope = retrieval_scores(
        set(plan.get("scope", [])),
        set(case.in_scope_ids) if case else set(),
        set(case.must_not_scope_ids) if case else set(),
    )
    cov = coverage_scores(scenarios, behaviours, valid_refs=pack_ids)
    pass_criteria = tuple(case.pass_criteria) if case else tuple(plan.get("metrics", []))
    orc = oracle_strength(steps, pass_criteria)
    fault = fault_class_coverage(scenarios, behaviours)
    phold = placeholder_scan(scenarios, steps, test_data, detail=detail)

    rub_ids = cites_only_real_ids(brief, pack_ids)
    rub_urls = no_invented_urls(brief, pack.summary_text())
    brief_ok = float(rub_ids.passed and rub_urls.passed)

    components = TPSComponents(
        fault_detection=fault.coverage,
        brief_groundedness=round((brief_ok + scope.precision) / 2, 3),
        coverage=round(cov.ac_recall * cov.matrix_completeness, 3),
        oracle_strength=orc.score,
        trajectory=trajectory,
    )
    out = tps(components)
    log.info("evaluate_plan %s: TPS=%s scope_leaked=%s", context_id, out.tps, scope.leaked)
    return PlanReport(
        context_id=context_id, seed=case.seed if case else "",
        tps=out.tps, components=out.components, scope=scope, coverage=cov, oracle=orc,
        placeholders=phold, fault=fault,
        rubrics=RubricsReport(cites_only_real_ids=rub_ids, no_invented_urls=rub_urls),
    )
