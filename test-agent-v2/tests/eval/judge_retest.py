"""Judge test-retest: one FIXED suite, judged K times.

Not a pytest test - it costs K real LLM calls and asserts nothing. Run by hand after any change to the
judge prompt or rubric:

    python tests/eval/judge_retest.py          # K=7
    K=11 python tests/eval/judge_retest.py

The suite must be fixed. A pipeline re-run regenerates scenarios, so its round-to-round movement
measures generator variance, not judge noise. Measured 2026-09-17: sigma=0.057 over 21 draws, median
0.320. See docs/RESEARCH-prompt-quality.md section 1.1.
"""

import asyncio
import itertools
import os
import statistics

from dotenv import find_dotenv, load_dotenv

# usecwd=True: load_dotenv() otherwise searches upward from THIS FILE and silently finds no VERTEX_*.
load_dotenv(find_dotenv(usecwd=True))

K = int(os.environ.get("K", "7"))

JUDGE_DIMS = ("ac_coverage", "atomicity", "testability", "traceability", "faithfulness",
              "negative_edge_coverage", "non_duplication")

SUMMARY = ("jira:LUZ-158230 — [eArchive] Health documents ZIP import in ePost. transfer.zip is "
           "imported into luz_docs_import; folder structure and metadata.json are preserved; OS "
           "artefacts are filtered; import is partial with a per-document error report; documents "
           "dedup by full path; HEALTH documents carry structured healthData.\n"
           "codegraph:axonivy-prod/luz_docs_import — the importing service.")


def fixture():
    """8 sound scenarios plus three planted flaws. A flawless suite gives the judge nothing to vary on
    and would understate the spread; an all-broken one would saturate it."""
    from common.testplan.models import TestPlan, TestScenario

    plan = TestPlan(id="plan:retest", context_id="run-retest", methodology=["api"],
                    metrics=["End-state verified — assert the stored document and the job-history record"],
                    test_design=["EP+BVA for metadata fields; decision table for per-document validation"])
    plan.scope = ["jira:LUZ-158230", "codegraph:axonivy-prod/luz_docs_import"]
    plan.out_of_scope = ["jira:LUZ-159471", "jira:LUZ-158243"]
    plan.test_kinds = ["security", "performance"]

    def sc(n, title, kind, desc, refs):
        return TestScenario(id=f"scenario:run-retest:{n}", plan_id=plan.id, title=title, kind=kind,
                            methodology="api", description=desc, rationale="", data_refs=["test-data:x"],
                            source_refs=refs, created_at="2026-09-17")

    good = "jira:LUZ-158230"
    return plan, [
        sc(1, "Import transfer.zip preserving folder structure and metadata", "happy",
           "Verifies every document lands in eArchive with its folder path and metadata intact.", [good]),
        sc(2, "Ignore OS artefact files during import", "happy",
           "Verifies .DS_Store/Thumbs.db/__MACOSX entries are skipped and not imported.", [good]),
        sc(3, "Import HEALTH document with structured healthData round-tripping", "happy",
           "Verifies healthData codes are stored and retrievable unchanged.", [good]),
        sc(4, "Skip an already-imported document on re-delivery (dedup by full path)", "happy",
           "Verifies a repeated ZIP does not duplicate documents, matched on full path.", [good]),
        sc(5, "Partially import a ZIP containing both valid and invalid documents", "negative",
           "Verifies valid documents import while invalid ones are reported per-document.", [good]),
        sc(6, "Reject a document whose metadata.json is malformed", "error",
           "Verifies a parse failure is reported for that document without failing the job.", [good]),
        sc(7, "Reject a document with an unknown document type", "negative",
           "Verifies an unsupported type is reported and other documents still import.", [good]),
        sc(8, "Reject an oversized ZIP at the documented limit", "boundary",
           "Verifies the size limit is enforced with a clear error.", [good]),
        # planted flaws - the judge should name all three by id
        sc(9, "Import transfer.zip preserving folder structure and metadata", "happy",
           "Verifies documents land with folder path and metadata intact.", [good]),   # dup of 1
        sc(10, "Exercise the performance case via api", "performance",
           "Exercise the performance case via api.", []),                              # ungrounded + vague
        sc(11, "Agentic-framework self-check ticket behaves correctly", "happy",
           "Verifies the QA tooling meta-ticket works.", ["jira:LUZ-159471"]),          # out of scope
    ]


async def main():
    from common.adk import agent_model
    from test_plan_definition.implement.assured.loop import judge_once

    model = agent_model()
    if model is None:
        raise SystemExit("VERTEX_* not configured - cannot measure the real judge.")

    plan, scenarios = fixture()
    print(f"Judge test-retest - IDENTICAL input, {K} independent samples")
    print(f"scenarios: {len(scenarios)} (8 sound, 1 near-duplicate, 1 ungrounded, 1 out-of-scope)\n")

    scores, dims = [], []
    for i in range(1, K + 1):
        v = await judge_once(plan, scenarios, SUMMARY, model)
        if v is None:
            print(f"  sample {i}: NO VERDICT (unparseable)")
            continue
        scores.append(round(v.score(), 3))
        dims.append({d: getattr(v, d) for d in JUDGE_DIMS})
        print(f"  sample {i}: score={v.score():.3f}  accept={v.accept}  issues={len(v.issues)}")

    if len(scores) < 3:
        print("\nnot enough verdicts to measure")
        return

    sd1 = statistics.stdev(scores)
    print(f"\nscores: {scores}")
    print(f"  median   {statistics.median(scores):.3f}")
    print(f"  min/max  {min(scores):.3f} / {max(scores):.3f}   SPREAD {max(scores) - min(scores):.3f}")
    print(f"  stdev of a SINGLE draw   sigma = {sd1:.3f}")

    # Does the shipped median-of-3 earn its cost? Every 3-subset of the draws. Needs K>=4: at K=3
    # there is exactly one subset and stdev of one value raises.
    if len(scores) >= 4:
        sd3 = statistics.stdev([statistics.median(c) for c in itertools.combinations(scores, 3)])
        cut = f" -> {100 * (1 - sd3 / sd1):.0f}% variance reduction" if sd1 else ""
        print(f"  stdev of a MEDIAN-OF-3   sigma = {sd3:.3f}{cut}")

    print("\nper-dimension spread (which criterion is least stable):")
    for d in JUDGE_DIMS:
        vals = [x[d] for x in dims]
        print(f"  {d:24s} {min(vals):.2f}-{max(vals):.2f}  spread {max(vals) - min(vals):.2f}")

    # Paired two-sample n for a 0.10 effect: n = 2*(1.96+0.84)^2*(sigma/delta)^2.
    n = max(1, round(15.7 * (sd1 / 0.10) ** 2))
    print(f"\nWith sigma={sd1:.3f}, resolving a 0.10 prompt improvement needs "
          f"n ~= {n} paired tickets per arm (alpha=.05, 80% power).")


if __name__ == "__main__":
    asyncio.run(main())
