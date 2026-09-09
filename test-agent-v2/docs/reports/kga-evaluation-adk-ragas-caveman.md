# kga-evaluation-adk-ragas.excalidraw — Caveman Explain

**Big idea: how robot SCORE the Knowledge-Gathering hunt. ADK grades the tool trajectory,
RAGAS grades what it retrieved and generated, and one golden set is the ground truth.
Roll it all into ONE number: the Pack Quality Score (PQS).** 📏🔍🏆

*(This the v2 doc set. Concept same as v1 — this a measurement design, framework-neutral.
Names kept current; no new architecture invented here.)*

---

## The measurement plane — three grader panels 🔵🟣

Top row, each panel scores the pipeline stage below it (dashed arrow = "measures"):
- **ADK · Trajectory & tool use** (blue) — tool_trajectory_avg_score · Tool Call Accuracy · Agent Goal Accuracy → *right tools, right order, deterministic*.
- **RAGAS · Retrieval** (purple) — Context Precision/Recall · Context Entities Recall · Noise Sensitivity (bleed guard) → *right nodes, no junk*.
- **RAGAS + ADK · Generation** (purple) — Faithfulness/hallucinations_v1 · Response Relevancy · final_response_match_v2 → *grounded + on-task, nothing invented*.

## The golden set — ground truth rock 🟠📦

Orange box + dark JSON box on the left: `seed` · `relevant_node_ids` · `must_not_retrieve` (hard negatives) · `key_entities` · `reference_understanding`. This the truth EVERY metric measures against.

## The KGA pipeline — what get scored 🟠🔵🟣🟢

Left to right, the real hunt:
**Seed ticket** (orange) → **Fan-out tiers** G2·G0·G1·G4 (blue) → **Frontier crawl (executor)** (blue) → **Per-node distill** (blue) → **Refine (interrogate)** (purple) → **Understanding = the answer** (purple) → **Approve** (green).
Two feeders push up into the crawl: **Memory bank (GCS index)** and **Atlassian (Jira · Confluence)** — two retrievers → one pack, score each retriever then the combined pack.

## The scoring harness — offline, out of band 🟢⬛

Bottom band: **Trajectory · Retrieval · Generation** scores → melt into **Pack Quality Score (PQS)** (green).
- **PR gate** (blue) — every commit, deterministic, no LLM: trajectory · node-overlap precision/recall · ROUGE.
- **Nightly / eval** (purple dashed) — LLM-judged, sampled: faithfulness · relevancy · hallucinations · noise.
- Dark boxes = the config + the sum: **EvalConfig (ADK test_config.json)** and
  **PQS = 0.30·Faithfulness + 0.25·CtxPrecision + 0.20·CtxRecall + 0.15·Relevancy + 0.10·Trajectory**.

## Rock color meaning 🎨

- 🟠 **orange** = the seed + the golden set (ground truth)
- 🔵 **blue** = ADK/trajectory grading · the crawl pipeline stages · the deterministic PR gate
- 🟣 **purple** = RAGAS retrieval/generation grading · the LLM-reasoning stages · the nightly LLM-judged eval
- 🟢 **green** = Approve · the Pack Quality Score
- ⬛ **dark navy** = code/config rocks (golden JSON · EvalConfig · the PQS formula)

## One grunt takeaway

**Golden set is the truth → ADK scores HOW it hunted → RAGAS scores WHAT it found and said →
weighted sum = one PQS to watch.** Deterministic checks gate every commit; LLM-judged checks
run nightly. Robot no longer *hope* the pack is good — robot MEASURE it. 🦣📏👍
