# tpd-evaluation-adk-testsuite.excalidraw — Caveman Explain

**Big idea: how robot SCORE the Test-Plan hunt. ADK grades the trajectory + how true the
brief stays to the pack; test-suite science grades coverage + whether the suite catches real
bugs. One golden set (a REAL executed plan) is truth. Roll into ONE number: Test-Plan Score (TPS).** 📏🧪🏆

*(This the v2 doc set. A measurement design, framework-neutral.
Names kept current; no new architecture invented here.)*

---

## The measurement plane — four grader panels 🔵🟣🟢🔴

Top row, each panel scores the pipeline stage below it (dashed "measures" arrow):
- **1 · ADK — Controller** (blue) — tool_trajectory_avg_score · define→approve→implement · rounds method→scope→metrics → *right tools + rounds, in order*.
- **2 · Groundedness — brief** (purple) — Faithfulness/hallucinations_v1 · Scope Precision/Recall · must_not_scope hard-neg gate → *scope true to the pack, no excluded nodes*.
- **3 · Coverage — suite** (green) — AC-Coverage Recall · Coverage-Matrix Completeness · Traceability scenario→AC → *every behaviour + partition, traced*.
- **4 · Fault detection** (red) — Oracle Strength (end-state ≠ 200) · Fault-class coverage (proxy now) · Mutation Score (gated: exec stage) → *a real regression fails a test*.

## The golden set — ground truth rock 🟠📦

Orange box + dark JSON on the left: `context_id` · `in_scope_ids` · `must_not_scope_ids` · `behaviours` (expected_partitions: happy/neg/boundary/error · fault_classes) · `reference_executed_plan: LUZ-156281 dunning`. Anchored to a **REAL executed plan** — the truth every metric measures against.

## The TPD pipeline — what get scored 🟢🔵🟣

Left to right: **Insight PACK (approved, from KGA)** (green) → **DEFINE · Stage A** method·scope·metrics·rounds (blue) → **TestPlan BRIEF** scope·metrics·method+confidence (purple) → **IMPLEMENT · Stage B** coverage matrix H·N·B·E (green) → **Scenarios / Steps + Test-data** (green) → **.feature (Gherkin export)** (purple).
Score the judgement engine (the brief) AND the generation engine (the suite) — a big suite that catches nothing is worse than a small one that does.

## The scoring harness — offline, out of band 🔵🟣🔴🟢⬛

Bottom, three grader tiers → one score:
- **PR gate · T0–T1** (blue, deterministic) — trajectory · scope P/R · must_not_scope · AC-recall · matrix · placeholder-leak.
- **Nightly · T2–T3** (purple, LLM-judged) — faithfulness · oracle strength · redundancy · Gherkin lint · execution-depth.
- **Mutation · T4** (red, gated on exec stage) — real PIT mutation score → replaces the proxy.
- All melt into **TEST-PLAN SCORE (TPS)** (green) — one number to watch (+ always emit components).
- Dark rocks = **EvalConfig (ADK test_config.json)** and **TPS = 0.30·FaultDetect + 0.25·Groundedness + 0.20·Coverage + 0.15·Oracle + 0.10·Trajectory**.

## Rock color meaning 🎨

- 🟠 **orange** = golden set (ground truth) · 🟢 **green** = pack input · IMPLEMENT/scenario stages · coverage panel · the TPS
- 🔵 **blue** = ADK/controller grading · DEFINE stage · deterministic PR gate
- 🟣 **purple** = groundedness grading · the BRIEF + .feature stages · nightly LLM-judged tier
- 🔴 **red** = fault-detection panel · the mutation tier (gated on the execution stage)
- ⬛ **dark navy** = code/config rocks (golden JSON · EvalConfig · the TPS formula)

## One grunt takeaway

**Golden set = a real executed plan → ADK scores HOW it planned + how true the brief →
test-suite science scores WHAT the suite covers and whether it catches real bugs →
weighted sum = one TPS.** T4 real-mutation is BLOCKED on the execution stage (the seam to the
QA-enhancement roadmap, Pillar 2). Big suite that catches nothing = worse than a small one that does. 🦣📏👍
