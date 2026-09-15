# Evaluating the Knowledge-Gathering Agent — Google ADK metrics + RAGAS

**Purpose.** The sibling reports ([`RESEARCH-agentic-qa-enhancements.md`](./RESEARCH-agentic-qa-enhancements.md),
[`RESEARCH-self-exploring-knowledge-gather.md`](./RESEARCH-self-exploring-knowledge-gather.md)) are about
*building* capability into the Testing Agent. This one is about **measuring** the first agent — the
**Knowledge-Gathering Agent (KGA)** — so every future change to it (the G0–G5 tiers, the explore loop, the
codegraph grounding) can be judged against a **repeatable score** instead of a hand-wave. It answers one
question: *given a seed ticket, how do we know the pack the KGA assembled is good?*

It draws on two established evaluation frameworks and maps each, metric by metric, onto the KGA's actual code
paths (`loop/crawl.py`, `explore/*`, `executor/refine.py`, `common/memory`):

1. **Google ADK Evaluation** — Google's Agent Development Kit ships an agent-eval harness whose metrics
   score two things a tool-using agent does: the **trajectory** (which tools it called, in what order) and
   the **final response** (is it correct, grounded, safe). These are the right lens for the KGA's
   *agentic control flow* — the `gather → refine → approve` tool sequence and the fan-out tier order.
2. **RAGAS (Retrieval-Augmented Generation Assessment)** — the de-facto metric set for RAG systems, split
   into **retrieval** metrics (did we fetch the right context?) and **generation** metrics (is the answer
   faithful to what we fetched?). These are the right lens for the KGA's *memory + crawl retrieval* — the
   G0 self-seed, the G1 Atlassian search, the `search_memory` tool, and the refine "understanding" it
   generates over the pack.

> **Diagram (open in Excalidraw, PNG renders inline):**
> - The KGA measurement plane — [`kga-evaluation-adk-ragas.excalidraw`](./kga-evaluation-adk-ragas.excalidraw) · [`.png`](./kga-evaluation-adk-ragas.png)

> ⚠️ **Honesty note.** The KGA is **not built on ADK** — it is a custom A2A agent (`a2a` server +
> `common.bridge` MCP). So we adopt ADK's **metric definitions and eval methodology**, not its runner, and
> port them into a small offline harness that drives the A2A agent directly. Where a claim below comes from a
> single vendor blog rather than primary docs, it is marked *(unverified)*.

> ✅ **Status (2026-09-04): IMPLEMENTED as the third agent.** The evaluation engine is now a
> first-class package [`src/test_evaluation/`](../src/test_evaluation/) — peer to
> `knowledge_gathering`/`test_plan_definition`, with its own metrics + `evaluate_pack` engine, golden
> spec, A2A executor, `server.py`, and MCP bridge (`test-evaluation-bridge`). It reads packs from the
> shared memory bank via `common`, so it never imports the other two agents. The offline gather/refine
> **harness** stays under [`tests/eval/`](../tests/eval/) (it drives the KGA, so it's test-side).
> Phases E0–E4 (see `tests/eval/README.md`). The deterministic PR gate (E0 trajectory +
> E1 node-overlap) and the deterministic parts of E3/E4 (entity recall, output-level noise
> sensitivity, PQS, rubrics, history) run with **no LLM and no network**; the E2 RAGAS
> faithfulness/relevancy tests skip unless the `eval` extra is installed. Ships with 3 golden seeds
> (`eval_rich`/`eval_bleed`/`eval_thin`) driving the real crawl offline; §7's 8–15 live-recorded
> seeds remain to be added. The "Where we are" paragraph below is the pre-implementation baseline.

---

## 0. TL;DR — the one gap and the one principle

**Where we started.** The KGA had **zero automated quality evaluation.** There were unit tests for wiring
(`tests/`), but nothing scored *the pack a gather produces*. Regressions were caught only by a human noticing
a bad run — exactly how the **memory-bleed → wrong-ticket** bug was found (refine asked ZIP-import questions
for a billing ticket), and the **0-links false-negative** (a thin ticket returned ~1 node and looked
"empty"). Both are **quality** failures a metric would catch; neither is a crash a unit test catches.

**The gap — now closed.** We couldn't answer "did this change make gathers *better* or *worse*?" — no golden
dataset, no retrieval score, no groundedness check, no trajectory assertion, so every tuning decision on
`_MAX_TERMS`, `max_web`, the explore-loop `_FOCUS_CAP`, or a new tier was **flown blind**. That gap is now
closed: the eval engine shipped as a third agent (`src/test_evaluation/`) with a deterministic PR gate; the
rest of this report is the design it was built from, and Appendix A is the as-built record.

**The principle.**

> **Score the pack, not the vibes.** A gather agent is a *retrieval* system with an *agentic* controller and
> a *generative* summarizer. Measure all three surfaces: (a) did the controller call the right tools in the
> right order (**ADK trajectory**), (b) did retrieval fetch the nodes a human QA would call relevant, and no
> junk (**RAGAS context precision/recall + noise sensitivity**), and (c) is the restated understanding
> grounded in those nodes with nothing invented (**RAGAS faithfulness / ADK hallucinations_v1**). Anchor
> every score to a small, human-curated **golden set** of seed → expected-pack pairs.

**The shape of the answer (as shipped).** One golden `EvalCase` JSON per seed (`golden/*.json`, an
ADK-EvalCase-shaped typed dataclass), a metric-per-stage matrix, and a `pytest`-driven offline harness that
runs deterministic metrics on every PR and the expensive LLM-judged metrics nightly — plus a runtime
`evaluate_pack` agent that scores a live pack on demand.

| Surface | Question | Framework | Headline metric |
|---|---|---|---|
| **Controller** | right tools, right order? | ADK | `tool_trajectory_avg_score` |
| **Retrieval** | right nodes, no junk? | RAGAS | Context Precision / Recall · Noise Sensitivity |
| **Generation** | understanding grounded + relevant? | RAGAS + ADK | Faithfulness · Response Relevancy · `hallucinations_v1` |
| **Regression** | did this PR make it worse? | both | golden-set deltas in CI |

![The KGA measurement plane. Bottom: the KGA pipeline (Seed → Fan-out G2·G0·G1·G4 → Frontier crawl → Distill → Refine → Understanding → Approve), fed by two retrievers (the GCS memory bank and Atlassian). Above it, three measurement panels each score the stage below via a dashed "measures" arrow: ADK trajectory/tool-use over the tool sequence, RAGAS retrieval over the crawl+memory, RAGAS+ADK generation over the understanding. A single human-curated golden set is the ground truth for every metric; the three score families combine into one weighted Pack Quality Score (PQS), consumed by a two-lane harness — a deterministic PR gate on every commit and an LLM-judged nightly run.](./kga-evaluation-adk-ragas.png)

---

## 1. Concepts & terms (glossary)

- **Pack / context pack** — everything a gather assembles for one `context_id`: the distilled **Notes**, the
  **link inventory** (`LinkRecord`s), declared **gaps**, and the `RunLog`. Persisted to the GCS memory bank.
- **Trajectory** — the ordered sequence of tool/skill invocations an agent makes for one task. For the KGA:
  the MCP tool sequence (`gather_knowledge → refine → … → approve`) and, one level down, the internal tier
  order (`G2 hypothesize → G0 self-seed → G1 search → G4 leads → crawl`).
- **Golden set / evalset** — a small, human-curated set of `(seed, expected_pack, reference_understanding)`
  triples. The ground truth every metric scores against. ADK calls one file an **EvalSet**, one seed an
  **EvalCase**, one turn an **Invocation**.
- **Retrieval surface** (KGA) — everything that *fetches context*: the frontier crawl (`loop/crawl.py`), the
  G0 memory self-seed (`explore/self_seed.py`), the G1 Atlassian search (`explore/atlassian_search.py`), the
  G4 grounding gate (`explore/ground_leads.py`), and the `search_memory`/`get_note` read tools.
- **Generation surface** (KGA) — everything that *writes prose from context*: the per-node distilled
  synopsis (`common.llm.distill`), the G2 hypothesized terms, and — most important — the refine
  **understanding** brief (`RefineResult.understanding`).
- **Reference-based vs reference-free** — a metric that needs a human-written ground truth (reference) vs one
  that scores from the run alone (e.g. faithfulness needs only answer+context, not a reference).
- **LLM-as-judge** — a metric computed by prompting a judge model (ADK default `gemini-2.5-flash`;
  RAGAS uses your configured LLM). Non-deterministic → sample N times, expect variance.
- **Deterministic metric** — computed by code, no LLM (ROUGE overlap, exact trajectory match, F1). Cheap,
  stable, PR-gate-able.

---

## 2. What "good" means for a gather agent

The KGA is not a chatbot; its "answer" is a **pack**. A good pack has five properties, and each maps to a
metric family:

| Property | Plain meaning | Failure we've actually seen | Metric family |
|---|---|---|---|
| **Complete** | it found the tickets/pages/repos a human QA would call relevant | 0-links crawl on a thin ticket (LUZ-159312: 1 node) | RAGAS **Context Recall**, **Entities Recall** |
| **Focused** | it did *not* drag in unrelated material | memory-bleed: billing seed pulled the ZIP-import cluster | RAGAS **Context Precision**, **Noise Sensitivity** |
| **Grounded** | the understanding cites the pack; nothing invented | external-LLM leads promoted without grounding (the G4 risk) | RAGAS **Faithfulness**, ADK **hallucinations_v1** |
| **On-task** | it answered *this* ticket, not a neighbour | refine restated the wrong domain | RAGAS **Response Relevancy**, **Topic Adherence** |
| **Well-driven** | the controller took the right tool path | skipped the dev-panel; a tier ran that shouldn't | ADK **tool_trajectory_avg_score**, **Tool Call Accuracy** |

The rest of the report turns that table into concrete metrics, thresholds, and a harness.

---

## 3. The KGA as an evaluation target

Before choosing metrics, pin down which stages are **deterministic** (trajectory metrics fit; expect exact
scores) vs **stochastic** (LLM-judged metrics; expect variance and sample). This matters because ADK's
`tool_trajectory_avg_score` defaults to a hard **1.0** — only legitimate for the deterministic parts.

| Stage | Code | Deterministic? | Retrieval / Generation | Notes |
|---|---|---|---|---|
| Seed probe | `executor/gather.py::_seed_probe` | ✅ | — | one `get_issue` read |
| G2 hypothesize | `explore/hypothesize.py` | ❌ LLM | Generation (terms) | flag-gated, default OFF |
| G0 memory self-seed | `explore/self_seed.py` | ✅ | **Retrieval** | pure index read, no LLM |
| G1 Atlassian search | `explore/atlassian_search.py` | ✅ | **Retrieval** | JQL/CQL, no LLM |
| G4 external leads | `explore/ask_llm.py` + `ground_leads.py` | ❌ LLM → ✅ gate | Generation → **Retrieval** | leads stochastic; grounding deterministic |
| Frontier crawl | `loop/crawl.py` | ✅ | **Retrieval** | bounded BFS; the executor |
| Per-node distill | `common.llm.distill` | ❌ LLM (or heuristic) | Generation | synopsis |
| G5 explore loop | `explore/loop.py` | ⚠️ mostly det. | orchestration | focus-derivation is token-based, no LLM |
| Refine understanding | `executor/refine.py` | ❌ LLM | **Generation** | the headline "answer" |

**Two retrieval sub-systems, one report.** RAGAS was built for a single retriever→generator. The KGA has
**two** retrievers feeding one generator: (i) the **crawl** (traverses the seed's neighborhood) and (ii) the
**memory** (G0/G1/`search_memory` over the GCS index). Evaluate them **separately** — the memory retriever is
where the bleed happens, and it deserves its own precision/recall — then evaluate the **combined** pack that
feeds refine.

---

## 4. Framework 1 — Google ADK Evaluation

### 4.1 The data model

ADK structures eval as **EvalSet → EvalCase → Invocation**. An EvalCase records, for one seed, the user
input, the **expected tool-use trajectory**, and the **reference final response**. Two ways to author:
`adk eval` on a saved `.evalset.json`, or `AgentEvaluator.evaluate()` inside `pytest`. Thresholds live in a
separate **EvalConfig** (`test_config.json`) so criteria can be tuned without touching cases.

### 4.2 The metric catalog (verbatim from `adk-python` v1.22.1 `PrebuiltMetrics`)

| Config key | Measures | Judge | Default threshold |
|---|---|---|---|
| `tool_trajectory_avg_score` | exact match of the tool-call sequence vs expected (match modes EXACT / IN_ORDER / ANY_ORDER) | deterministic | **1.0** |
| `response_match_score` | ROUGE-1 word overlap of final response vs reference | deterministic | **0.8** |
| `response_evaluation_score` | Vertex AI coherence score of the response | Vertex metric | — |
| `final_response_match_v2` | LLM-judged **semantic** match to the reference (replaces brittle ROUGE) | LLM (`gemini-2.5-flash`, `num_samples=5`) | 0.8 |
| `hallucinations_v1` | splits the response into sentences, checks each is **grounded** in the provided context/tool outputs | LLM | — |
| `rubric_based_final_response_quality_v1` | LLM-judged response quality against **custom rubrics** you write | LLM | 0.8 |
| `rubric_based_tool_use_quality_v1` | LLM-judged tool-usage quality against custom rubrics | LLM | — |
| `safety_v1` | harmlessness of the response | LLM / Vertex | 0.8 |
| `per_turn_user_simulator_quality_v1` | quality of a simulated multi-turn user (for interactive eval) | LLM | — |

`EvalConfig` shape:

```json
{
  "criteria": {
    "tool_trajectory_avg_score": 1.0,
    "response_match_score": 0.8,
    "final_response_match_v2": {
      "threshold": 0.8,
      "judge_model_options": { "judge_model": "gemini-2.5-flash", "num_samples": 5 }
    },
    "hallucinations_v1": { "threshold": 0.8, "judge_model_options": { "judge_model": "gemini-2.5-flash" } }
  }
}
```

### 4.3 What applies to the KGA (and what doesn't)

- **`tool_trajectory_avg_score` — YES, high value.** The KGA's outer trajectory (`gather → refine → approve`)
  and inner tier order are the *most deterministic, most regression-prone* part. Assert IN_ORDER on the tier
  sequence and on the crawl's fetch-kind order. This is what would have caught the **dev-panel omission**
  (parent/subtasks + dev-status not called → 1-node crawl): the expected trajectory includes a
  `get_issue_dev_status` call; a regression that drops it fails the metric.
- **`hallucinations_v1` — YES, critical.** This is the single most important ADK metric for the KGA. The
  refine understanding must be grounded in the gathered notes. It directly guards the **G4 external-LLM**
  risk ("lead generator, not source of truth") and the **memory-bleed** ("understanding drifted to the wrong
  domain"). Context = the pack's notes; response = the understanding.
- **`final_response_match_v2` — YES for refine.** Semantic (not ROUGE) match of the understanding to a
  human-written reference understanding. Prefer over `response_match_score` because the understanding is
  paraphrastic — ROUGE-1 punishes valid rewordings.
- **`response_match_score` (ROUGE) — LIMITED.** Useful only for the *deterministic* summary line
  (`summarize_gather`: "N nodes, M links, K gaps"), where exact tokens matter. Not for prose.
- **`safety_v1` — LOW priority.** The KGA is read-only over internal Atlassian; harmlessness is not the risk.
  Keep it as a cheap always-on floor, not a focus.
- **`rubric_based_*` — YES, later.** Write KGA-specific rubrics ("does the understanding name the AC?", "are
  all cited ids real pack nodes?") once the golden set exists.

---

## 5. Framework 2 — RAGAS

RAGAS scores a RAG pipeline on **retrieval** and **generation**, plus an **agentic** group. The KGA is
literally a retrieval-augmented system (crawl+memory → distill/understanding), so RAGAS is the closer fit for
pack *content* quality. Each RAGAS sample is `{user_input, retrieved_contexts, response, reference}`.

### 5.1 Retrieval metrics — score the pack's node set

| Metric | Definition | Needs reference | KGA mapping |
|---|---|---|---|
| **Context Precision** | fraction of retrieved contexts that are actually relevant (are the top items signal, not noise?) | reference/answer | of the pack's notes, how many are genuinely about *this* ticket. **Catches memory-bleed.** |
| **Context Recall** | fraction of the relevant contexts that were retrieved (did we miss anything?) | reference | of the human's known-relevant tickets/pages, how many the gather found. **Catches the 0-links false-negative.** |
| **Context Entities Recall** | of the key entities in the ground truth, how many appear in retrieved context | reference entities | did the pack surface the right LUZ keys, components, endpoints, repos? |
| **Noise Sensitivity** | how often the system is swayed by irrelevant retrieved chunks (lower = better) | reference | the **memory gravity-well**: does an irrelevant node change the understanding? |

### 5.2 Generation metrics — score the understanding

| Metric | Definition | Needs reference | KGA mapping |
|---|---|---|---|
| **Faithfulness** | fraction of claims in the answer that are supported by the retrieved context (groundedness) | no (answer+context) | is every statement in the understanding traceable to a pack note? Same intent as ADK `hallucinations_v1`. |
| **Response Relevancy** | does the answer directly address the question | no | does the understanding address *this ticket's* AC, not a neighbour's? |
| **Factual Correctness** | claim-level factual accuracy vs reference | reference | for seeds where we have a canonical understanding. |
| **Semantic Similarity** | embedding similarity of answer vs reference | reference | cheap deterministic backstop for `final_response_match_v2`. |

### 5.3 Agentic / tool-use metrics

| Metric | Definition | KGA mapping |
|---|---|---|
| **Tool Call Accuracy** | correct tools chosen with correct params | did gather call the dev-status panel / the right JQL project scope? Overlaps ADK trajectory. |
| **Agent Goal Accuracy** | binary: was the user's goal achieved? | did the run end in an approved, on-domain pack? |
| **Topic Adherence** | did the agent stay on the assigned topic across turns | the **G5 explore-loop drift** guard — does round-N focus stay on the seed's topic or wander into the memory well? |

### 5.4 The KGA twist: precision/recall need a *node-set* ground truth, not text chunks

Classic RAGAS compares retrieved text chunks to a reference answer via an LLM. The KGA's retrieved units are
**identified nodes** (`jira:LUZ-…`, `confluence:…`, `codegraph:…`) — so we get a **cheaper, deterministic**
option: define the golden **relevant node-id set** per seed and compute precision/recall/F1 by **set
overlap**, no LLM needed. Reserve the LLM-judged RAGAS variants for the fuzzy cases (a page that's *partly*
relevant). This hybrid (deterministic set-overlap for ids + LLM-judge for prose) is the harness's backbone.

---

## 6. The mapping — KGA stage × metric matrix (core deliverable)

This is the table to implement against. "Det." = deterministic/cheap (PR gate). "Judge" = LLM-judged
(nightly).

| KGA stage / artifact | Primary metric(s) | Framework | Kind | Ground truth needed |
|---|---|---|---|---|
| Outer tool sequence `gather→refine→approve` | `tool_trajectory_avg_score` (IN_ORDER) | ADK | Det. | expected tool list |
| Inner tier order `G2→G0→G1→G4→crawl` | `tool_trajectory_avg_score` + Tool Call Accuracy | ADK/RAGAS | Det. | expected tier list per seed shape |
| Crawl fetch calls (dev-panel, remote-links) | Tool Call Accuracy | RAGAS | Det. | expected fetch kinds |
| **Memory retriever** (G0/G1/`search_memory`) node set | **Context Precision / Recall / F1** (set-overlap) | RAGAS | Det. | golden relevant-id set |
| Memory retriever entity coverage | Context Entities Recall | RAGAS | Judge | golden entity list |
| **Combined pack** node set | Context Precision / Recall + **Noise Sensitivity** | RAGAS | Det.+Judge | golden relevant-id set |
| Per-node synopsis | Faithfulness (vs node body) | RAGAS | Judge | — |
| **Refine understanding** groundedness | **Faithfulness** / `hallucinations_v1` | RAGAS/ADK | Judge | — |
| Refine understanding correctness | `final_response_match_v2` + Semantic Similarity | ADK/RAGAS | Judge+Det. | reference understanding |
| Refine understanding on-task | Response Relevancy | RAGAS | Judge | — |
| `summarize_gather` count line | `response_match_score` (ROUGE) | ADK | Det. | expected counts |
| G5 explore-loop rounds | **Topic Adherence** + per-round Noise Sensitivity | RAGAS | Judge | seed topic ref |
| Whole run | Agent Goal Accuracy (approved, on-domain) | RAGAS | Judge | binary label |
| Declared gaps honesty | custom rubric (`rubric_based_final_response_quality_v1`) | ADK | Judge | rubric |

**Composite "Pack Quality Score" (PQS).** For dashboards, a single weighted mean, weighting **groundedness
and precision highest** because our real incidents were bleed + hallucination, not recall:

```
PQS = 0.30·Faithfulness + 0.25·ContextPrecision + 0.20·ContextRecall
    + 0.15·ResponseRelevancy + 0.10·TrajectoryScore
```

Report the components too — a single number hides which surface regressed.

---

## 7. The golden dataset (evalset) design

The harness is only as good as the golden set. Curate **8–15 seeds** spanning the shapes that break the KGA:

| Seed shape | Example | Why it's in the set |
|---|---|---|
| Rich, well-linked ticket | LUZ-158390 | happy path; high recall expected |
| **Thin container** (title only) | LUZ-159312 | the 0-links false-negative; tests G1 + parent climb |
| **Bleed-prone** billing seed | luz_finance ticket | tests precision/noise vs the ZIP-import well |
| Ticket with dev-panel repo | any with PRs | tests codegraph + Tool Call Accuracy |
| Confluence page seed | a spec page | non-Jira retrieval |
| Cross-domain umbrella | epic w/ subtasks | recall + focus tension |

Per seed, author a small JSON (ADK EvalCase-compatible) with the **minimum viable ground truth**:

```json
{
  "seed": "LUZ-159312",
  "expected_trajectory": ["gather_knowledge", "refine", "approve"],
  "expected_tiers": ["G0_self_seed", "G1_atlassian_search", "crawl"],
  "relevant_node_ids": ["jira:LUZ-156281", "jira:LUZ-159312", "confluence:12345", "codegraph:axonivy-prod/luz_finance"],
  "must_not_retrieve_ids": ["jira:LUZ-158390", "codegraph:epost/zip-import"],
  "key_entities": ["luz_finance", "invoice", "charge", "LUZ-156281"],
  "reference_understanding": "This ticket adds … The AC requires … Grounded in luz_finance repo endpoints …"
}
```

- `relevant_node_ids` → Context Recall/Precision by set overlap.
- `must_not_retrieve_ids` → **hard-negative** list; any appearance is a precision/noise failure (this
  encodes the bleed guard directly).
- `key_entities` → Context Entities Recall.
- `reference_understanding` → `final_response_match_v2` / Faithfulness anchor.

Store the golden set in `test-agent/src/test_evaluation/golden/*.json` (loaded by `golden.py`) with the
recorded Atlassian fixtures alongside the harness in `tests/eval/fixtures/atlassian/`; keep both in git
(they're the spec of "good"). *As built, the seed keys are the synthetic `eval_rich`/`eval_bleed`/`eval_thin`
cases; the live LUZ-keyed 8–15 set of §7 is the pending coverage work.*

---

## 8. Engine + harness design — **as built**

**Offline, deterministic-first, LLM-judged-nightly** — mirroring the codebase's discipline (blocking LLM calls
are `asyncio.to_thread`-offloaded; expensive tiers default OFF). The build landed in **two pieces** because
scoring is useful both in CI *and* at runtime: a deployable **scoring engine** and a test-side **offline
harness**. Appendix A carries the full file-by-file layout; this section is the shape and the rationale.

### 8.1 The scoring engine — `src/test_evaluation/` (a deployable third agent)

The engine that turns a persisted pack into a score is a **first-class agent**, peer to
`knowledge_gathering` / `test_plan_definition` — not a test fixture. That choice is what lets the same code run
as a required PR check *and* as an optional runtime quality gate the pipeline calls after `approve`.

```
src/test_evaluation/
  models.py            # every metric result a typed dataclass (no bare dicts cross module boundaries)
  metrics/             # trajectory · node_overlap · entities · noise · topic · ragas_judge · pqs · rubrics · history
  golden.py  golden/*.json   # the §7 EvalCases (eval_rich / eval_bleed / eval_thin shipped)
  engine.py            # evaluate_pack(bank, context_id, case) -> EvalReport  (deterministic, no LLM/net)
  agent.py  executor/  server.py  bridge/  monitoring.py   # the A2A + MCP surface (see Appendix A)
```

`engine.py::evaluate_pack` reads the **run-scoped** pack exactly as refine does
(`common.interrogate.pack.load_pack(bank, context_id)`) plus the restated understanding
(`bank.read_understanding`), and scores retrieval (node-overlap + hard-negative leak gate), entity coverage,
and the fabrication rubrics into a PQS — **without importing the other two agents**. Deployed as Cloud Run
`module.tev` and exposed to Claude as the `evaluate_pack` MCP tool.

### 8.2 The offline harness — `tests/eval/` (test-side, drives the *real* KGA)

Scoring the pack tells you nothing unless you can **produce** a pack deterministically. That job — driving a
real gather/refine offline — lives test-side, because it imports `knowledge_gathering` and must not pollute
`test_evaluation`'s cross-agent independence.

```
tests/eval/
  harness.py                 # run_gather_offline / run_refine_offline + RunTrace + RecordedAtlassianClient
  fixtures/atlassian/*.json  # recorded Jira/Confluence responses, one per golden seed
  test_metrics.py  test_eval_deterministic.py  test_engine.py  test_eval_judged.py
```

The harness drives the KGA over the **same in-process A2A stack the wiring tests use** — a Starlette
`TestClient` posting JSON-RPC `message/send` — with a `RecordedAtlassianClient` (fixture-backed, and it
**records every call** for tool-use trajectory) and a `FakeBucket`-backed `MemoryBank`. So a gather runs the
*actual* crawl + fan-out but touches nothing external. Refine is driven through
`common.interrogate.loop.refine` with heuristic answers (no LLM). Each run yields a `RunTrace` exposing what a
human reviews: `reply`, `node_ids`/`node_texts`, `tiers`, `fetch_kinds`, `tool_calls`, `understanding`.

### 8.3 Two lanes of run

1. **PR gate (seconds, no LLM, no network).** Replay each golden seed through the harness (real crawl,
   recorded Atlassian client, `FakeBucket` bank) and score trajectory + node-overlap; the deterministic parts
   of E3/E4 (entity recall, output-level noise sensitivity, PQS, fabrication rubrics, history) run here too.
   `pytest tests/eval/test_metrics.py tests/eval/test_eval_deterministic.py tests/eval/test_engine.py` is the
   required check — gate on a clean working tree so an eval pass can't mask an uncommitted edit.
2. **Nightly / `eval:` label (minutes, LLM).** `test_eval_judged.py` adds `ragas` faithfulness /
   response-relevancy over the understanding (optionally ADK `hallucinations_v1` / `final_response_match_v2`).
   These **skip cleanly** unless the `[eval]` extra is installed (`ragas_judge.available()`); post the
   **PQS + component deltas** vs the last main-branch baseline.

**Determinism & flakiness.** LLM-judged metrics vary run-to-run — sample `num_samples≥3`, compare **means**,
and gate on a **delta band** (e.g. "faithfulness dropped >0.05 vs baseline"), never an absolute pass/fail on a
single sample. Deterministic metrics gate absolutely; that is why the required check carries only them.

**Reuse, don't rebuild.** The engine reads the **same artifacts a human reviews** — the run-scoped pack
(`load_pack`), the `understanding`, and (in the harness) the gather `reply` / `RunLog`-derived tiers — rather
than re-deriving anything. Nothing in the scoring path re-crawls or re-queries; it scores what was persisted.

---

## 9. What the metrics would have caught (retro-fit to real incidents)

Each past KGA incident (from the project memory) maps to a metric that would have flagged it **before** a
human noticed — the strongest argument for building this:

| Incident (memory note) | Metric that flags it | How |
|---|---|---|
| **memory-bleed → wrong ticket** (billing seed asked ZIP-import questions) | Context Precision ↓, Noise Sensitivity ↑, Faithfulness ↓ | `must_not_retrieve_ids` for the billing seed lists the ZIP-import nodes; any appearance fails precision, and the drifted understanding fails faithfulness vs the (correct) pack. |
| **0-links false-negative** (thin ticket → 1 node) | Context Recall ↓ | the thin seed's golden `relevant_node_ids` has the parent + siblings; a 1-node crawl scores near-zero recall. |
| **crawler misses parent + dev panel** | `tool_trajectory_avg_score` ↓, Tool Call Accuracy ↓ | expected trajectory includes the dev-status + parent fetch; dropping them fails the order match. |
| **interrogation asks nothing** ("high confidence", 0 questions) | Agent Goal Accuracy = 0, Response Relevancy ↓ | an empty interrogation on a rich seed = goal not achieved; the "understanding" is generic → low relevancy. |
| **G4 hallucinated lead promoted** (hypothetical, the risk G4 is designed against) | Faithfulness ↓, `hallucinations_v1` ↓ | an ungrounded lead in the pack introduces unsupported claims in the understanding. |
| **explore-loop drift** (G5 wanders off-seed) | Topic Adherence ↓ | round-over-round focus compared to the seed topic reference. |

---

## 10. Phased roadmap — **shipped**

Cheap, deterministic value first; expensive LLM judging last — the same "default-OFF, earn-the-cost" pattern
the agents already follow. All five phases landed (Appendix A is the file-by-file record); the remaining work
is **coverage** (§7's 8–15 live seeds) and E4's render/alert tail, not machinery.

- **E0 — Golden set + trajectory (no LLM). ✅ done.** 3 golden seeds shipped (`eval_rich`/`eval_bleed`/
  `eval_thin`; §7's 8–15 pending). `metrics/trajectory.py` scores the tier + fetch-kind sequences as a
  **required PR check** — regression safety on the control flow.
- **E1 — Node-overlap retrieval scores (no LLM). ✅ done.** `metrics/node_overlap.py` gives Context
  Precision/Recall/F1 by id-set overlap + the `must_not_retrieve` hard-negative leak gate. This alone catches
  bleed **and** the 0-links case. Still a required PR gate.
- **E2 — Groundedness judging (LLM, nightly). ✅ done, gated.** `metrics/ragas_judge.py` scores `ragas`
  Faithfulness + Response Relevancy over the refine understanding; **skips** without the `[eval]` extra.
  Optional ADK `hallucinations_v1` is the second-opinion seam.
- **E3 — Entity recall + noise + topic adherence. ✅ done, deterministic.** `metrics/entities.py`,
  `metrics/noise.py` (counterfactual drift), `metrics/topic.py` — all run with no LLM, so the explore loop is
  tunable against a drift number instead of by eye.
- **E4 — Rubrics + dashboard (ongoing). ◑ partial.** PQS (`metrics/pqs.py`), the two deterministic
  fabrication rubrics + declared semantic rubrics (`metrics/rubrics.py`), and the append-only history
  primitive (`metrics/history.py`) shipped; the render + main-branch-regression alert tail is the remaining
  ongoing work.

---

## 11. Constraints & gotchas (from this system's own history)

- **Cloud Run timeout is the hard ceiling — which is why the runtime engine is deterministic-only.** Never run
  **LLM-judged** eval inside the agent request path — the event-loop-blocking Vertex call already killed an
  instance (`ERROR_TIMEOUT`). This shaped the split: the runtime `evaluate_pack` agent scores a pack **inside**
  a request, but *only the deterministic metrics* (node-overlap + entity + fabrication rubrics), and even those
  run in a worker thread (`asyncio.to_thread`) so a large pack never stalls the event loop. The LLM-judged tier
  (RAGAS faithfulness/relevancy) stays **out of band** — pytest/CI + the offline harness, never in `execute()`.
- **GCS memory state is shared and mutable.** A gather **writes** the index; running the harness against the
  live bucket pollutes it (and a redeploy has silently wiped state before). The harness uses a **temp/isolated
  bank** and recorded fixtures — never the prod `GCS_BUCKET`.
- **The working tree, not the commit, is what runs.** `gcloud builds submit` and pytest both use the working
  tree — an eval "pass" on uncommitted edits can mask an inconsistent commit. Gate on a clean tree.
- **LLM-judged metrics are non-deterministic and cost tokens.** Default them OFF in the PR gate; sample and
  compare means nightly. Deterministic set-overlap + trajectory carry the required-check weight.
- **`tool_trajectory_avg_score` default 1.0 is only valid on deterministic stages.** The G2/G4 LLM tiers and
  the distiller are stochastic — assert trajectory on the deterministic skeleton (crawl fetch order, tier
  presence), not on stochastic sub-steps.
- **RAGAS/ADK assume one retriever.** The KGA has two (crawl + memory) — score them separately *and*
  combined, or the memory-bleed signal gets averaged away.

---

## 12. Sources

Primary (preferred):
- [Google ADK — Why evaluate agents](https://google.github.io/adk-docs/evaluate/) · [Evaluation criteria reference](https://adk.dev/evaluate/criteria/)
- [`adk-python` v1.22.1 `eval_metrics.py` (PrebuiltMetrics enum)](https://github.com/google/adk-python/blob/v1.22.1/src/google/adk/evaluation/eval_metrics.py)
- [`adk-docs` evaluate/index.md](https://github.com/google/adk-docs/blob/main/docs/evaluate/index.md)
- [RAGAS — List of available metrics](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/) · [Agentic / tool-use metrics](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/agents/)

Secondary / corroborating (blogs — treated as *unverified* where they exceed the primary docs):
- [Testing with ADK — Agent evaluations (Google Cloud, Medium)](https://medium.com/google-cloud/testing-with-agent-development-kit-agent-evaluations-76a9eec27965)
- [Evaluate Amazon Bedrock Agents with Ragas (AWS)](https://aws.amazon.com/blogs/machine-learning/evaluate-amazon-bedrock-agents-with-ragas-and-llm-as-a-judge/)
- [RAG Evaluation: Metrics, Tools, and the Context Gap (Atlan)](https://atlan.com/know/how-to-evaluate-rag-systems-explained/)

*Cross-check status: ADK metric names + EvalConfig schema corroborated against the `adk-python` source and the
official criteria docs. RAGAS metric names + categories corroborated against the official `docs.ragas.io`
metric index. Default thresholds (`1.0`, `0.8`) are from the ADK criteria docs; treat exact judge-model
defaults as version-dependent (`gemini-2.5-flash` / `gemini-flash-latest` across releases).*

---

## Appendix A — Implementation plan (phase by phase) — **as built**

> **This appendix is the as-built record, not a forward plan.** The §10 roadmap (E0–E4) shipped, but the
> engine landed differently than first sketched: it was **promoted from a tests-only harness to a
> first-class, deployable third agent**. So the code is split across **two** locations (the original plan put
> everything under `tests/eval/`):
> - the scoring **engine** is a peer agent — **`src/test_evaluation/`** — alongside `knowledge_gathering` /
>   `test_plan_definition`, deployed as its own Cloud Run service and reachable at runtime via the
>   `evaluate_pack` MCP tool (see *"The runtime evaluation agent"* below);
> - the offline **harness + tests** stay under **`tests/eval/`** — the harness imports `knowledge_gathering`
>   to drive a *real* gather, so it must live test-side to keep `test_evaluation` free of cross-agent deps.
>
> Deterministic phases (E0–E1, plus the deterministic parts of E3/E4) are required PR checks; the E2 RAGAS
> tier runs nightly / on an `eval:` label and **skips** cleanly unless the `[eval]` extra is installed.

### Layout (as built)

```
src/test_evaluation/               # the deployed third agent — scores a PERSISTED pack from the bank
  models.py                        # every metric result a typed dataclass (no bare dicts cross modules)
  metrics/
    trajectory.py   node_overlap.py   entities.py   noise.py   topic.py
    ragas_judge.py  pqs.py            rubrics.py     history.py
  golden.py  golden/*.json          # eval_rich · eval_bleed · eval_thin (3 shipped; §7's 8–15 pending)
  engine.py                         # evaluate_pack(bank, context_id, case) -> EvalReport
  agent.py  executor/  server.py  bridge/  monitoring.py   # A2A + MCP surface (runtime agent, below)

tests/eval/                        # out-of-band harness + tests (never in the agent request path)
  harness.py                       # run_gather_offline / run_refine_offline + RunTrace + RecordedAtlassianClient
  fixtures/atlassian/*.json        # recorded Jira/Confluence responses (3, one per golden seed)
  test_metrics.py                  # E0/E1 metric math (PR gate)
  test_eval_deterministic.py       # E0 trajectory + E1 node-overlap, seed-driven (PR gate)
  test_engine.py                   # the engine + the A2A executor, end-to-end (PR gate)
  test_eval_judged.py              # E2 RAGAS · E3 entity/noise/topic · E4 PQS/rubrics/history (nightly)
  README.md
```

### Shared scaffolding (`tests/eval/harness.py`)

The harness drives the **real** KGA in-process — no HTTP hop, no Cloud Run, no live Atlassian/GCS — over the
same in-process A2A stack the wiring tests use (Starlette `TestClient` + JSON-RPC `message/send`), so a gather
runs the actual crawl + fan-out but touches nothing external.

- **`RecordedAtlassianClient`** — a duck-typed `AtlassianClient` backed by `fixtures/atlassian/<name>.json`
  (`get_issue` / `get_issue_remote_links` / `get_issue_dev_status` / `search_jql` / `search_cql` / `get_page`).
  It **records every call** (`.calls`) for tool-use trajectory assertions; missing dev-status data → `{}`
  (no crash, no dev links). Record fixtures once from a real `build_client()` run and commit — no network in CI.
- **`FakeBucket`-backed `MemoryBank`** (from `tests/conftest`) — a harness run never touches the prod
  `GCS_BUCKET`; each `RunTrace` carries its own isolated bank.
- **`run_gather_offline(seed, *, client, bank=None, flags=None, text=None, context_id=None)`** — the core driver:

```python
# tests/eval/harness.py (abridged)
def run_gather_offline(seed, *, client, bank=None, flags=None, text=None, context_id=None) -> RunTrace:
    bank = bank or MemoryBank(FakeBucket())
    context_id = context_id or f"eval-{seed}"
    with env(flags or {}):                              # e.g. {"KGA_EXPLORE_LOOP": "1"}
        body = _send(TestClient(_app(bank, client)), text or f"gather {seed}", context_id=context_id)
    return RunTrace(seed=seed, reply=_all_text(body), bank=bank, context_id=context_id, client=client)
```

  The crawl stamps every note with `run_id == context_id` (B0 run-scoping), so **reuse `trace.context_id`
  for refine** — otherwise `load_pack` sees nothing.
- **`run_refine_offline(bank, ctx, *, seed)`** — drives `common.interrogate.loop.refine` to completion with
  heuristic answers (no LLM) on a fresh event loop, returning a `RefineResult` (`.understanding`,
  `.confidence`, `.insights`, …).

`RunTrace` exposes exactly what a human reviews: `reply`, `node_ids` / `node_texts` (from
`bank.load_index()`), `tiers` (derived from the gather-reply markers), `fetch_kinds` (node-kind prefixes),
`tool_calls` (the recorded client calls), and `understanding` (after a refine run).

---

### E0 — Golden set + trajectory gate  ·  ~2–3 days · no LLM · **PR-required**

**Goal.** Lock the control flow: `gather → refine → approve` order and the internal tier/fetch sequence.
**Status: done** — `metrics/trajectory.py` + `test_eval_deterministic.py::test_tier_trajectory` /
`test_fetch_kind_trajectory` ship green.

1. Authored the golden EvalCases as `src/test_evaluation/golden/*.json` (loaded by `golden.py::load_golden`).
   **3 shipped** — `eval_rich` (happy path), `eval_bleed` (hard-negative), `eval_thin` (0-links → B1 climb) —
   covering the §7 shapes that break the KGA; §7's full 8–15 live-recorded seeds remain to be added. Each case
   is a typed `EvalCase` (`models.py`) with `seed`, `fixture`, `depth`, `shape`, `expected_trajectory`,
   `expected_tiers`, `expected_fetch_kinds`, `relevant_node_ids`, `must_not_retrieve_ids`, `key_entities`,
   `min_recall`/`min_precision`, `reference_understanding`.
2. Recorded `tests/eval/fixtures/atlassian/<fixture>.json` for each (one per golden seed; committed).
3. Built the shared scaffolding above (`tests/eval/harness.py`).
4. `src/test_evaluation/metrics/trajectory.py`:

```python
def trajectory_score(actual: list[str], expected: list[str], mode="in_order") -> float:
    # mode: "exact" | "in_order" | "any_order"  (mirrors ADK tool_trajectory_avg_score)
    if mode == "any_order": return len(set(expected) & set(actual)) / len(expected)
    if mode == "exact":     return float(actual == expected)
    it = iter(actual)                                    # in_order: subsequence match
    return float(all(e in it for e in expected))
```

   It scores two traces the `RunTrace` derives: (a) the **tier trace** — `RunTrace.tiers`, which of the
   fan-out tiers fired, matched by reply-signature markers in the gather output (`G2_hypothesize`,
   `B1_climb`, `G0_self_seed`, `G1_atlassian_search`, `G4_leads` — the B-phase de-bias vocabulary, not the
   original G-tier sketch), scored `in_order`; and (b) the **fetch-kind trace** — `RunTrace.fetch_kinds`,
   the node-kind prefixes of the persisted nodes (`jira`/`confluence`/`codegraph`/…), scored `any_order`.
   This is what catches the dev-panel/parent regression.
5. `test_eval_deterministic.py::test_tier_trajectory` + `::test_fetch_kind_trajectory` — assert
   `trajectory_score(...) == 1.0` per golden seed (parametrized over `load_golden()`).
6. **CI:** run `pytest tests/eval/test_metrics.py tests/eval/test_eval_deterministic.py tests/eval/test_engine.py`
   as a **required** check; gate on a clean working tree (`git status --porcelain` empty) so an eval pass
   can't mask an uncommitted edit.

**Done when:** every golden seed passes trajectory 1.0 in CI on a clean tree; a deliberately reverted
dev-panel fetch turns the check red.

---

### E1 — Node-overlap retrieval scores  ·  ~2–3 days · no LLM · **PR-required**

**Goal.** Score *what the pack retrieved* deterministically — the bleed + 0-links guards.
**Status: done** — `metrics/node_overlap.py` + `test_eval_deterministic.py::test_retrieval_scores` ship green.

1. `src/test_evaluation/metrics/node_overlap.py` — returns a typed `RetrievalScore` (`models.py`), not a
   bare dict (the "typed dataclasses everywhere" refactor), and also surfaces `missing` (relevant ids the
   pack dropped):

```python
def retrieval_scores(retrieved: set[str], relevant: set[str],
                     hard_neg: set[str] = frozenset()) -> RetrievalScore:
    tp = retrieved & relevant
    precision = len(tp) / len(retrieved) if retrieved else 0.0
    recall    = len(tp) / len(relevant)  if relevant  else 1.0
    f1        = 2*precision*recall/(precision+recall) if (precision+recall) else 0.0
    return RetrievalScore(precision=precision, recall=recall, f1=f1,
                          leaked=sorted(retrieved & hard_neg),   # must be empty — the bleed gate
                          missing=sorted(relevant - retrieved))
```

2. `retrieved` = `RunTrace.node_ids`; scored against the case's `relevant_node_ids` + `must_not_retrieve_ids`.
3. Per-seed thresholds live on the `EvalCase` (`min_recall`, `min_precision`, defaulting `0.8`/`0.7`); the
   test **asserts `leaked == []` hard** (any hard-negative is a fail — this *is* the bleed gate), then
   `recall >= min_recall` and `precision >= min_precision`.
4. The bleed-prone seed can be run with/without the explore-loop / B-phase flags (`harness.run_gather_offline`
   takes a `flags=` dict) to prove the de-bias improves precision (regression-locks B4/B5).
5. Folded into `test_eval_deterministic.py`; still a required PR check.

**Done when:** the thin-container seed's recall and the billing seed's `leaked==[]` both pass; injecting the
hard-negative into the pack makes the billing seed leak and fail (see `test_engine.py::test_evaluate_pack_flags_a_leak`).

---

### E2 — Groundedness + relevancy judging  ·  ~1 week · LLM · **nightly / `eval:`**

**Goal.** Score the refine **understanding**: is it grounded in the pack and on-task?
**Status: done, LLM-gated** — `metrics/ragas_judge.py` + `test_eval_judged.py::test_ragas_faithfulness_relevancy`
ship; the test **skips** unless the `[eval]` extra is installed (`ragas_judge.available()`).

1. `ragas` (+ pandas / datasets / google-adk) is the `[eval]` optional-dependency in `pyproject.toml`, so CI
   installs it only for the judged job; the deterministic PR gate needs none of it.
2. `tests/eval/harness.run_refine_offline(bank, ctx, seed=…)` drives `common.interrogate.loop.refine` to
   completion (heuristic answers, no LLM) and the judged tests capture `RunTrace.understanding`.
3. `src/test_evaluation/metrics/ragas_judge.py` — returns a typed `RagasScore` (`models.py`); the heavy
   `ragas` imports live **inside** `judge()` so importing the module never requires the extra:

```python
def available() -> bool:
    return importlib.util.find_spec("ragas") is not None

def judge(seed_summary, understanding, note_synopses, reference, *, llm=None, embeddings=None) -> RagasScore:
    from ragas import evaluate
    from ragas.dataset_schema import EvaluationDataset
    from ragas.metrics import answer_relevancy, faithfulness
    ds = EvaluationDataset.from_list([{
        "user_input": seed_summary, "response": understanding,
        "retrieved_contexts": note_synopses or [""], "reference": reference,
    }])
    kwargs = {k: v for k, v in (("llm", llm), ("embeddings", embeddings)) if v is not None}
    row = evaluate(ds, metrics=[faithfulness, answer_relevancy], **kwargs).to_pandas().iloc[0]
    return RagasScore(**{k: float(row[k]) for k in ("faithfulness", "answer_relevancy") if k in row})
```

   Configure `llm`/`embeddings` on Vertex (reuse `common.llm`); a different family than the generator is
   ideal (§3.4). Optionally add ADK `hallucinations_v1` via `google-adk` for a second groundedness opinion.
4. **Non-determinism:** `num_samples>=3`, compare the **mean** to the last main-branch baseline, gate on a
   **delta band** (fail if `faithfulness` drops `>0.05` vs baseline), never an absolute single-run pass/fail.
5. `test_eval_judged.py`; runs on a schedule + the `eval:` PR label; posts the scores as a PR comment.

**Done when:** nightly reports faithfulness + relevancy per seed with a baseline; an injected ungrounded
sentence in the understanding drops faithfulness below the band.

---

### E3 — Entity recall · noise · topic adherence  ·  ~1 week · LLM · **nightly**

**Goal.** E1 answered *"did the crawl fetch the right node-ids?"* deterministically. E3 covers the three
things node-overlap cannot see: did the right **facts** surface, did **irrelevant** context corrupt the
answer, and does the **explore loop** stay on-seed. Each metric maps to a distinct KGA failure surface.
**Status: done, deterministic** — all three shipped as `metrics/entities.py`, `metrics/noise.py`,
`metrics/topic.py` and, crucially, run **without an LLM**: they score the *same real understanding* an LLM
judge would, driven fully offline, so they land in `test_eval_judged.py` but **always run** (no `[eval]` gate).

**1. Context Entities Recall — did the pack surface the right domain entities?**

Node-overlap counts *containers*; a pack can fetch the right epic yet miss that it references the
`luz_finance` repo or the `/luz_docs/api/{tenant}/documents` endpoint. Entities = the concrete named things:
Jira keys, component/repo names, REST endpoints, enums, security classes.

- *Deterministic tier* (cheap): match the golden `key_entities` against the pack's note text (`synopsis` +
  `title`). Code identifiers / issue keys are exact-match-friendly, so this catches most cases with no LLM.
- *LLM upgrade* (`ragas.metrics.ContextEntitiesRecall`): entity extraction from reference + contexts, for
  fuzzy variants (`luz_finance` vs "Luz Finance service").

```python
# src/test_evaluation/metrics/entities.py — deterministic tier (returns a typed EntitiesScore)
def entities_recall(note_texts: list[str], key_entities: list[str]) -> EntitiesScore:
    hay = " ".join(note_texts).lower()
    found = [e for e in key_entities if e.lower() in hay]
    return EntitiesScore(recall=len(found) / len(key_entities) if key_entities else 1.0,
                         found=found, missing=[e for e in key_entities if e.lower() not in hay])
```

Keep the curated `key_entities` list authoritative (LLM entity extraction is itself noisy); reach for the
RAGAS metric only for fuzzy seeds. Report `missing` — it names the referent the pack dropped.

**2. Noise Sensitivity — does one irrelevant node corrupt the answer?**

This is **the memory-bleed metric at the output level.** Precision (E1) catches the irrelevant ZIP-import node
being *retrieved*; noise sensitivity catches whether it actually *changed the understanding* — exactly the
bleed incident. Two ways to run it:

The **counterfactual perturbation proxy** shipped (higher-signal, KGA-specific) — literally simulate the
bleed. `metrics/noise.py::drift_score` is the deterministic core; `test_eval_judged.py::test_noise_sensitivity_output_level`
wires the causal experiment: gather+refine a **clean** pack, then link the hard-negative into the seed's
`issuelinks` so it actually enters a **noisy** pack, re-gather+refine, and measure the drift:

```python
# metrics/noise.py — returns a typed NoiseScore
def drift_score(baseline: str, perturbed: str, injected_terms: list[str]) -> NoiseScore:
    b, p = baseline.lower(), perturbed.lower()
    leaked = [t for t in injected_terms if t.lower() in p and t.lower() not in b]
    return NoiseScore(noise_sensitivity=len(leaked)/len(injected_terms) if injected_terms else 0.0,
                      leaked_terms=leaked)

# test_eval_judged.py (abridged) — the causal bleed experiment, fully offline
und_a = run_refine_offline(clean.bank, "bleed-clean",  seed="jira:LUZ-701").understanding
# … inject LUZ-799 into LUZ-701's issuelinks, re-gather into noisy.bank (LUZ-799 now in the pack) …
und_b = run_refine_offline(noisy.bank, "bleed-noisy",  seed="jira:LUZ-701").understanding
assert drift_score(und_a, und_b, ["ZIP import", "address enrichment"]).noise_sensitivity == 0.0
```

  A robust agent ignores the noise (`und_b ≈ und_a`, `noise_sensitivity == 0.0`); a noise-sensitive one lets
  the injected node's entities/claims leak into `und_b`. This is a **causal** test, not correlational —
  toggle a de-bias flag (B4 hub penalty, B5 grounding gate) and watch the injected terms stop leaking. The
  direct RAGAS `NoiseSensitivity` metric can layer on top for a fuzzy-context second opinion.

**3. Topic Adherence — does the G5 explore loop stay on-seed?** (only when `KGA_EXPLORE_LOOP=1`)

The loop derives round-N focus from round N-1's node titles (`salient_tokens`), which can **drift** into the
memory gravity well — the `self-explore-memory-bias` failure (a thin seed drifting to a 43-node wrong-domain
pack). You already have the trace: `explore.loop` writes per-round `reflections` to GCS state
(`"round N: focus=…, promoted=…"`).

- Capture each round's `focus` + promoted-node titles; reference topic = the seed's own domain (title/labels/
  AC, or a golden `seed_topic`).
- `metrics/topic.py::adherence(round_terms, seed_terms)` scores the fraction of a round's focus terms still
  on the seed's topic (deterministic token-overlap, no LLM); `adherence_curve(rounds, seed_terms)` plots it
  as a **per-round curve** — a monotone decline is drift; a cliff at round K says set
  `KGA_EXPLORE_MAX_ROUNDS = K`. `ragas.metrics.TopicAdherenceScore` can layer on for fuzzy topics.

The payoff: the loop knobs (`_FOCUS_CAP`, `KGA_EXPLORE_MAX_ROUNDS`, the B3 topic-coherence stop, B4 hub
penalty, B5 grounding gate) become **tunable against a number** instead of by eye.

**Done when:** the two runs in the memory-bias diagram (codegraph-grounded vs ungrounded thin-seed) produce
*measurably different* noise-sensitivity and topic-adherence — the metric can tell the good 12-node pack from
the drifted 43-node one.

---

### E4 — Rubrics + PQS dashboard  ·  ongoing · LLM

**Goal.** E0–E3 produce a scatter of per-surface scores. E4 turns it into **one trend number to watch** plus
**domain-specific quality gates** no off-the-shelf metric knows. "Ongoing" because rubrics accrete (each new
incident → a new rule) and the trend is a living artifact. **Status: PQS + deterministic rubrics + history
shipped** (`metrics/pqs.py`, `metrics/rubrics.py`, `metrics/history.py`); the LLM semantic rubrics + the
render/alert dashboard remain the ongoing tail.

**1. PQS — the weighted composite** (`metrics/pqs.py`) — `WEIGHTS` keys are the `PQSComponents` field names;
`pqs()` returns a typed `PQSResult` that always carries its components:

```python
WEIGHTS = {"faithfulness": .30, "ctx_precision": .25, "ctx_recall": .20,
           "relevancy": .15, "trajectory": .10}
def pqs(components: PQSComponents) -> PQSResult:
    score = sum(w * getattr(components, k) for k, w in WEIGHTS.items())
    return PQSResult(pqs=round(score, 3), components=components)   # ALWAYS carries both
```

At **runtime** (`engine.py::evaluate_pack`) the components are filled from the persisted pack:
`faithfulness` = the two fabrication rubrics passing (`cites_only_real_ids` ∧ `no_invented_urls`),
`ctx_precision`/`ctx_recall` from `node_overlap`, `relevancy` from `entities_recall`, and `trajectory` left
**neutral (1.0)** — the tier trajectory needs the gather reply, which only the offline harness has, so the
harness scores it and the runtime agent leaves it neutral.

Faithfulness + precision weigh highest because the *real* incidents were bleed + drift, not missing recall: a
thin pack is a **visible** failure a human catches; a high-recall-but-bled pack looks *full* and fools you, so
the silent failure modes get the heavier weights. Trajectory is lowest — E0 already gates it deterministically,
so in PQS it's a tie-breaker. **Always emit the components** next to the number: a 0.04 PQS drop could be all
faithfulness or all recall, and you need to know which surface regressed to act.

**2. Rubric-based metrics — where domain expertise enters.** LLM-judged pass/fail rules specific to the KGA
(ADK `rubric_based_final_response_quality_v1` or RAGAS `RubricsScore`, via the EvalConfig `rubrics` array in
§4.2). Each rubric turns a real failure mode into a *permanent* regression test:

The two ID/URL fabrication rubrics shipped **deterministic** (`metrics/rubrics.py`, regex + set membership)
and gate every run — including at runtime inside `evaluate_pack`; the two semantic rubrics are declared as
data (`SEMANTIC_RUBRICS`) and run **LLM-judged** through an injected `judge(question, text) -> bool`
(`judge_semantic`), so the module imports with no LLM dependency.

| Rubric | Catches | Ties to | Kind |
|---|---|---|---|
| `cites_only_real_ids` | references a ticket/node not in the pack | G4 hallucination guard (output level) | **Det. (shipped)** |
| `no_invented_urls` | fabricated URL not in the pack text | fabrication guard | **Det. (shipped)** |
| `names_the_ac` | a generic "high confidence" summary, no real AC | the "interrogation asks nothing" false-positive | LLM (`judge_semantic`) |
| `declares_gaps_honestly` | papering over unknowns when the pack has gaps | gaps-honesty | LLM (`judge_semantic`) |

**3. Dashboard / trend / alerting.** The **history** primitive shipped (`metrics/history.py`); the render +
alert lane is the ongoing tail.

- **Persist** — `append_run(path, timestamp=…, commit=…, pqs=…, components=…, per_seed=…)` writes one
  `HistoryRecord` per line to an append-only JSONL (locally a file; the nightly runner mirrors it to
  `gs://…/memory/eval/history.jsonl`). The **caller** stamps `timestamp`/`commit` — the eval code stays
  clock-free (mirroring the workflow "deterministic/replayable" rule). `load_history` + `regressed(current,
  baseline, band=0.05)` give the main-branch baseline comparison.
- **Render** a PQS-over-time trend with per-component sparklines (reuse the excalidraw/HTML renderer in
  `docs/`) — *not yet built*.
- **Alert** on a main-branch PQS drop `> 0.05`, **naming the offending component** (route through the repo's
  existing Telegram hooks) — *not yet built*.

E4 is last because it needs E2+E3's scores to be *stable* (you can't trend noisy numbers) and rubrics are only
worth writing once you have real failure examples to encode. It's the **quality ratchet**: E0–E1 stop
control-flow regressions, E2–E3 measure content quality, E4 makes that quality monotonically improve.

**Done when:** a PQS trend line exists with per-component breakdown, and a regression on any surface trips an
alert with the offending component named.

---

### The runtime evaluation agent (engine + A2A + MCP + deploy) — **the change from the original plan**

The original Appendix A stopped at a `tests/eval/` harness. The build went further: the scoring engine became
a **deployable third agent** so a pack can be scored *at runtime* — an optional quality gate the pipeline
calls after `approve`, not only a CI check. This is why the code lives in `src/test_evaluation/`.

- **`engine.py::evaluate_pack(bank, context_id, case=None, *, trajectory=1.0) -> EvalReport`** — reads the
  **run-scoped** pack the way refine does (`common.interrogate.pack.load_pack(bank, context_id)`) plus the
  restated understanding (`bank.read_understanding`), scores retrieval + entities + fabrication rubrics, and
  composes the PQS. Fully deterministic — no network, no LLM. When a golden `EvalCase` matches the seed it
  supplies the relevant/hard-negative ids + key entities; without one, only the citation rubrics are
  meaningful. `trajectory` stays neutral at runtime (see the E4 note) and is scored by the offline harness.
- **`agent.py` + `executor/base.py`** — the A2A surface. One skill, `evaluate-pack`; the
  `TestEvaluationExecutor` handles `evaluate <context_id>` (or `score …`), pulls the context id from the
  message or the A2A `context_id`, and runs `evaluate_pack` in a worker thread (`asyncio.to_thread`) so a
  large pack never stalls the event loop. Read-only over the shared bank.
- **`server.py`** — the FastAPI/A2A app (`test_evaluation.server:app`): health routes (requires only
  `GCS_BUCKET`), the agent-card + JSON-RPC routes, `BearerAuthMiddleware`, and the shared Cloud SQL / in-memory
  task store. **It never imports the other two agents.**
- **`bridge/mcp_server.py`** — the A2A→MCP bridge (`test-evaluation-bridge`, entry point in `pyproject.toml`):
  exposes `evaluate_pack(context_id)` (+ `agent_card` / `send_raw`) to Claude over stdio or streamable-HTTP.
- **`monitoring.py`** — a `TEV`-namespaced `LoggingToggle`, independent of the KGA/TPD/COMMON namespaces.

**Deployment.** Wired as the **third Cloud Run service** — terraform `module.tev` in
`deployments/services.tf`, gated by `var.deploy_test_evaluation` (mirrors `module.tpd`, no Atlassian; it only
needs the memory bank). The service runs `uvicorn test_evaluation.server:app` (port 8081) with the MCP bridge
as a sidecar (`python -m test_evaluation.bridge`); `outputs.tf` exposes `tev_bridge_url`, and
`tools/install-mcp.{sh,cmd}` registers it with Claude.

**Pipeline integration.** In the Testing-Agent flow (`common/bridge/prompts.py`), evaluation is an **optional,
read-only, never-blocking** gate — *step 3b*: after `approve`, if the `test-evaluation` server is connected,
call `evaluate_pack(context_id)` and surface the PQS + retrieval/rubric breakdown; on a leak (leaked
hard-negatives) or low recall, offer to re-gather (`exclude=…` / `repo=…`) before planning.

---

### Sequencing & effort — **as built**

| Phase | Depends on | LLM? | Gate | Status |
|---|---|---|---|---|
| E0 trajectory | — | no | PR-required | **done** |
| E1 node-overlap | E0 scaffolding | no | PR-required | **done** |
| E2 RAGAS faithfulness/relevancy | E0 + refine driver | yes | nightly / `eval:` | **done, skips without `[eval]`** |
| E3 entities · noise · topic | E2 driver | no (deterministic core) | nightly, always-run | **done** |
| E4 PQS · rubrics · history | E2/E3 scores | partial (LLM semantic rubrics) | dashboard | **PQS/det-rubrics/history done; render+alert pending** |
| Runtime agent + deploy | E0–E4 engine | no | Cloud Run service + pipeline gate | **done** |

Suite: **264 → 292 pass** after the engine + harness landed (the E2 RAGAS tests skip without the extra).
The remaining work is **coverage, not machinery**: §7's 8–15 live-recorded golden seeds (only the 3 synthetic
`eval_*` seeds ship today), and E4's render/alert dashboard tail.
