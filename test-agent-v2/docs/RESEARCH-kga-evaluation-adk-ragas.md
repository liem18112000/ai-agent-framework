# Evaluating the Knowledge-Gathering Agent — a 3-layer framework (Google ADK + RAGAS)

> **Structure update (2026-09-15):** the two golden sets are now ONE unified dataset — `golden/<seed>.json` with nested `pack` / `plan` view sub-objects (the loaders `load_golden()` / `load_golden_plans()` / `load_canaries()` / `load_canary_plans()` project each view; `golden_plans/` has been removed, canaries stay under `golden/canary/`). The scorers moved into an **`engine/` package** — `engine/pack.py::evaluate_pack`, `engine/plan.py::evaluate_plan`, and `engine/loaders.py` (shared pack/plan loading), re-exported from `test_evaluation.engine`. Path references below that say `golden_plans/`, `engine.py`, or `plan_engine.py` describe the pre-merge layout.


**Purpose.** The sibling reports ([`RESEARCH-tpd-assured-generation.md`](./RESEARCH-tpd-assured-generation.md),
[`RESEARCH-test-executor-agent.md`](./RESEARCH-test-executor-agent.md)) are about *building* capability into
the Testing Agent. This one is about **measuring** the first agent — the
**Knowledge-Gathering Agent (KGA)** — so every future change to it (the exploration tiers, the explore loop,
the codegraph grounding) can be judged against a **repeatable score** instead of a hand-wave. It answers one
question: *given a seed ticket, how do we know the pack the KGA assembled is good?*

It organizes the answer with a **three-layer evaluation framework** — measure the *artifact*, the *process*
that produced it, and its *downstream effect* — and fills each layer with metrics from two established sources:

1. **Google ADK Evaluation** — Google's Agent Development Kit ships an agent-eval harness whose metrics score
   two things a tool-using agent does: the **trajectory** (which tools it called, in what order) and the
   **final response** (is it correct, grounded, safe). These are the right lens for **Layer 2** — the KGA's
   *agentic control flow*: the `gather → refine → approve` tool sequence and the fan-out tier order.
2. **RAGAS (Retrieval-Augmented Generation Assessment)** — the de-facto metric set for RAG systems, split into
   **retrieval** metrics (did we fetch the right context?) and **generation** metrics (is the answer faithful
   to what we fetched?). These are the right lens for **Layer 1** — the KGA's *pack content*: the memory
   self-seed, the Atlassian search, the `search_memory` tool, and the refine "understanding" over the pack.

> **Diagram (open in Excalidraw, PNG renders inline):**
> - The KGA measurement plane — [`kga-evaluation-adk-ragas.excalidraw`](./kga-evaluation-adk-ragas.excalidraw) · [`.png`](./kga-evaluation-adk-ragas.png)

> ✅ **Status (2026-09-15): IMPLEMENTED and ADK-native.** The evaluation engine is a first-class package
> [`src/test_evaluation/`](../src/test_evaluation/) — peer to `knowledge_gathering` / `test_plan_definition` /
> `admin_agent`. Since the **ADK-native cutover**, the eval agent (like the KGA it scores) is an ADK
> `RouterAgent` served through `common.adk.serve` (`to_a2a`), so we now have **both** a deterministic offline
> harness *and* ADK's own runner. One package scores **two** artifacts: `evaluate_pack` (KGA pack → **Pack
> Quality Score / PQS**) and `evaluate_plan` (TPD plan → Test-Plan Score / TPS, see the sibling report). It
> reads packs from the shared memory bank via `common`, so it never imports the other agents. The
> deterministic PR gate (trajectory + node-overlap + entities + rubrics + PQS) runs with **no LLM and no
> network**; the LLM-judged tier (RAGAS faithfulness/relevancy + ADK judged criteria) is **provider-sourced
> (Claude-on-Vertex, I8)** and skips cleanly without the `[eval]` extra or `VERTEX_*` creds. Ships 3 golden
> seeds (`eval_rich`/`eval_bleed`/`eval_thin`) driving the real crawl offline; §9's 8–15 live-recorded seeds
> remain the coverage work. Appendix A is the as-built record.

---

## 0. TL;DR — the framework, the gap, the principle

**The framework.** A pack can *look* excellent and still be useless downstream, so we measure it on three
layers (the [agentic-QA evaluation spec](./agentic-qa-eval-framework.html)):

| Layer | What it measures | KGA question | Framework |
|---|---|---|---|
| **Layer 1 — Artifact** | the pack itself | right nodes, no junk; understanding grounded + on-task? | **RAGAS** retrieval + generation |
| **Layer 2 — Process** | how it got there | right tools, right order; goal achieved? | **ADK** trajectory + tool-use |
| **Layer 3 — Downstream** | the real signal | does this pack corrupt or enable the plan built on it? | noise/topic drift + the TPD handoff |

**Where we started.** The KGA had **zero automated quality evaluation.** There were unit tests for wiring
(`tests/`), but nothing scored *the pack a gather produces*. Regressions were caught only by a human noticing
a bad run — exactly how the **memory-bleed → wrong-ticket** bug was found (refine asked ZIP-import questions
for a billing ticket), and the **0-links false-negative** (a thin ticket returned ~1 node and looked
"empty"). Both are **quality** failures a metric catches; neither is a crash a unit test catches.

**The gap — now closed.** We couldn't answer "did this change make gathers *better* or *worse*?" — no golden
dataset, no retrieval score, no groundedness check, no trajectory assertion, so every tuning decision on
`_MAX_TERMS`, `max_web`, the explore-loop caps, or a new tier was **flown blind**. That gap is now closed: the
eval engine shipped as the third agent (`src/test_evaluation/`) with a deterministic PR gate; the rest of this
report is the design it was built from, restructured around the three layers.

**The principle.**

> **Score the pack, not the vibes.** A gather agent is a *retrieval* system (Layer 1) with an *agentic*
> controller (Layer 2) whose output only matters by what it *enables* (Layer 3). Anchor every score to a
> small, human-curated **golden set** of seed → expected-pack pairs, and keep a few deliberately-bad **canary
> seeds** that must always score low — if a canary ever scores high, the eval pipeline is broken, not the agent.

![The KGA measurement plane. Bottom: the KGA pipeline (Seed → Fan-out tiers → Frontier crawl → Distill → Refine → Understanding → Approve), fed by two retrievers (the GCS memory bank and Atlassian). Three measurement layers score it: Layer 1 (RAGAS retrieval + generation over the pack and understanding), Layer 2 (ADK trajectory/tool-use over the tool sequence), Layer 3 (downstream — noise/topic drift and the handoff to the plan agent). A single human-curated golden set plus canary seeds is the ground truth; the score families combine into one weighted Pack Quality Score (PQS), consumed by three lanes — a deterministic PR gate, an LLM-judged nightly run, and the ADK-native runner.](./kga-evaluation-adk-ragas.png)

---

## 1. The three-layer framework (the organizing spine)

> **Diagram (open in Excalidraw, PNG renders inline):**
> - The three layers at a glance — [`kga-eval-three-layers.excalidraw`](./kga-eval-three-layers.excalidraw) · [`.png`](./kga-eval-three-layers.png)

![The three-layer evaluation framework for the KGA. A thin pack-pipeline spine on the left (Seed → Fan-out → Crawl → Distill → Refine → Understanding → Approve). Three stacked layer bands, top to bottom: Layer 1 Artifact (blue, RAGAS retrieval + generation, ~90% of PQS), Layer 2 Process (amber, ADK trajectory, 10% of PQS), Layer 3 Downstream (green, dashed — Noise Sensitivity / Topic Adherence / the TPD plan handoff, not folded into PQS). Each band has a dashed "measures" arrow into the pipeline; Layer 1 + Layer 2 converge into the PQS composite on the right, while Layer 3 feeds a separate dashed TPS chip.](./kga-eval-three-layers.png)

The framework comes from the [agentic-QA evaluation spec](./agentic-qa-eval-framework.html): **a plan can look
excellent and still catch no bugs — so measure the artifact, the process that produced it, and what it does in
the field.** Applied to the KGA, whose "artifact" is a *pack*:

- **Layer 1 — Artifact quality (the pack).** Everything about the output itself: did retrieval fetch the nodes
  a human QA would call relevant and no junk (**Context Precision / Recall / Entities**), and is the restated
  understanding grounded in those nodes with nothing invented and on-task (**Faithfulness / Response
  Relevancy / fabrication rubrics**). This is where RAGAS lives, and it carries the heaviest PQS weight because
  our real incidents were bleed + hallucination.
- **Layer 2 — Agent process (how it got there).** The controller's behaviour, not its output: did it call the
  right tools in the right order (`gather → refine → approve`), fire the right fan-out tiers, hit the dev-panel
  it needs; did the run achieve its goal; is it consistent across N runs. This is where ADK lives.
- **Layer 3 — Downstream effectiveness (the real signal).** A pack is an *intermediate* artifact — its true
  quality is whether it *enables* a good test plan and doesn't *corrupt* it. Layer 3 is the hardest to measure
  directly, so today it is a set of proxies: **Noise Sensitivity** (does one irrelevant node change the
  understanding — the bleed, at the output level), **Topic Adherence** (does the explore loop drift off-seed),
  and, ultimately, the **plan quality** the sibling TPD report scores on the pack this agent hands off.

Every metric below is tagged with its layer. The composite PQS spans Layers 1–2 (Layer 3's downstream signal
is scored by the TPD report, not folded into the PQS number).

---

## 2. Concepts & terms (glossary)

- **Pack / context pack** — everything a gather assembles for one `context_id`: the distilled **Notes**, the
  **link inventory** (`LinkRecord`s), declared **gaps**, and the `RunLog`. Persisted to the GCS memory bank.
- **Trajectory** — the ordered sequence of tool/skill invocations an agent makes for one task. For the KGA:
  the MCP tool sequence (`gather_knowledge → refine → … → approve`) and, one level down, the internal tier
  order and crawl fetch-kind order.
- **Golden set / evalset** — a small, human-curated set of `(seed, expected_pack, reference_understanding)`
  triples. The ground truth every metric scores against. ADK calls one file an **EvalSet**, one seed an
  **EvalCase**, one turn an **Invocation**.
- **Canary seed** — a deliberately-degraded golden seed (a bled pack, a thin container) whose score *must* stay
  low. A canary scoring high means the metric or judge is broken, not the agent (from the HTML spec's
  calibration protocol, §11).
- **Retrieval surface** (KGA) — everything that *fetches context*: the frontier crawl
  (`gather/crawl/crawl.py`), the memory self-seed and Atlassian search (`gather/explore/*`), and the
  `search_memory` / `get_note` read tools.
- **Generation surface** (KGA) — everything that *writes prose from context*: the per-node distilled synopsis
  (`common.llm` distiller), the hypothesized terms, and — most important — the refine **understanding** brief.
- **Reference-based vs reference-free** — a metric that needs a human-written ground truth vs one that scores
  from the run alone (faithfulness needs only answer+context, not a reference).
- **LLM-as-judge** — a metric computed by prompting a judge model. In this system the judge is
  **provider-sourced** (Claude-on-Vertex via `agent_model()`), never an OpenAI/Gemini default (I8).
  Non-deterministic → sample N times, expect variance.
- **Deterministic metric** — computed by code, no LLM (set overlap, exact trajectory match, substring recall).
  Cheap, stable, PR-gate-able.

---

## 3. What "good" means for a gather agent

The KGA is not a chatbot; its "answer" is a **pack**. A good pack has five properties; each maps to a metric
family and sits in one of the three layers:

| Property | Layer | Plain meaning | Failure we've actually seen | Metric family |
|---|---|---|---|---|
| **Complete** | 1 | it found the tickets/pages/repos a human QA would call relevant | 0-links crawl on a thin ticket (LUZ-159312: 1 node) | RAGAS **Context Recall**, **Entities Recall** |
| **Focused** | 1 | it did *not* drag in unrelated material | memory-bleed: billing seed pulled the ZIP-import cluster | RAGAS **Context Precision** (+ hard-negative gate) |
| **Grounded** | 1 | the understanding cites the pack; nothing invented | ungrounded external-LLM lead promoted | RAGAS **Faithfulness**, `cites_only_real_ids` / `no_invented_urls` rubrics |
| **On-task** | 1 | it answered *this* ticket, not a neighbour | refine restated the wrong domain | RAGAS **Response Relevancy** |
| **Well-driven** | 2 | the controller took the right tool path | skipped the dev-panel; a tier ran that shouldn't | ADK **tool_trajectory_avg_score**, Tool Call Accuracy |
| **Non-corrupting** | 3 | irrelevant context didn't change the answer, and the loop stayed on-seed | bleed changed the understanding; explore loop drifted to a 43-node wrong domain | **Noise Sensitivity**, **Topic Adherence** |

---

## 4. The KGA as an evaluation target

Before choosing metrics, pin down which stages are **deterministic** (trajectory metrics fit; expect exact
scores) vs **stochastic** (LLM-judged; expect variance and sample). This matters because ADK's
`tool_trajectory_avg_score` defaults to a hard **1.0** — only legitimate on the deterministic parts. Code paths
below are the **current by-agent layout** (`gather/` owns crawl + explore; `refine/` owns the interrogation).

| Stage | Code | Deterministic? | Layer | Notes |
|---|---|---|---|---|
| Seed probe | `gather/**` seed read | ✅ | 2 | one `get_issue` read |
| Hypothesize terms | `gather/explore/*` (LLM planner) | ❌ LLM | 1 (gen) | always-on when Vertex configured |
| Memory self-seed | `gather/explore/seeds/*` | ✅ | 1 (retr) | pure index read, no LLM |
| Atlassian search | `gather/explore/*` (JQL/CQL) | ✅ | 1 (retr) | no LLM |
| External leads → grounding gate | `gather/explore/*` | ❌ LLM → ✅ gate | 1 | leads stochastic; grounding deterministic |
| Frontier crawl | `gather/crawl/crawl.py` | ✅ | 1 (retr) | bounded BFS; the executor |
| Per-node distill | `common.llm` distiller | ❌ LLM (or heuristic) | 1 (gen) | synopsis |
| Explore loop | `gather/explore/*` | ⚠️ mostly det. | 3 | focus-derivation is token-based, no LLM |
| Refine understanding | `refine/*` | ❌ LLM | 1 (gen) | the headline "answer" |

**Two retrieval sub-systems, one report.** RAGAS was built for a single retriever→generator. The KGA has
**two** retrievers feeding one generator: (i) the **crawl** (traverses the seed's neighborhood) and (ii) the
**memory** (self-seed / search / `search_memory` over the GCS index). Evaluate them **separately** — the memory
retriever is where the bleed happens, and it deserves its own precision/recall — then evaluate the **combined**
pack that feeds refine.

---

## 5. Layer 1 — Artifact quality (the pack) · RAGAS

The pack is the artifact. Layer 1 scores its *content* — retrieval on the left, generation on the right — and
composes them into the PQS.

> **Diagram:** Layer 1 in detail — [`kga-layer1-artifact-ragas.excalidraw`](./kga-layer1-artifact-ragas.excalidraw) · [`.png`](./kga-layer1-artifact-ragas.png)

![Layer 1 (Artifact quality · RAGAS). Two retrievers — the frontier crawl and memory — converge into one combined pack node set, which splits into two sub-surfaces. Left: RETRIEVAL, a deterministic node-set overlap (a Venn of Retrieved ∩ Golden-relevant giving Context Precision/Recall, a hard-negative leak gate, Context Entities Recall) with the RetrievalScore code chip. Right: GENERATION over the understanding — Faithfulness and Response Relevancy (judge), cites_only_real_ids and no_invented_urls (det), and the opt-in semantic rubrics. Both sub-surfaces converge into the PQS formula chip (0.30 faithfulness + 0.25 precision + 0.20 recall + 0.15 relevancy + 0.10 trajectory).](./kga-layer1-artifact-ragas.png)

### 5.1 Retrieval metrics — score the pack's node set

Each RAGAS sample is `{user_input, retrieved_contexts, response, reference}`. The KGA twist: retrieved units
are **identified nodes** (`jira:LUZ-…`, `confluence:…`, `codegraph:…`), so precision/recall are a **cheap,
deterministic set-overlap**, no LLM needed — reserve LLM-judged RAGAS for the fuzzy cases.

| Metric | Definition | Kind | KGA mapping |
|---|---|---|---|
| **Context Precision** | fraction of retrieved contexts that are actually relevant | **Det.** (set overlap) | of the pack's notes, how many are genuinely about *this* ticket. **Catches memory-bleed.** |
| **Context Recall** | fraction of the relevant contexts retrieved | **Det.** (set overlap) | of the human's known-relevant nodes, how many the gather found. **Catches the 0-links false-negative.** |
| **Hard-negative leak gate** | did any `must_not_retrieve` node appear? | **Det.** | the bleed guard — *any* appearance is a hard fail, scored 0. |
| **Context Entities Recall** | of the key entities in the ground truth, how many appear in retrieved text | **Det.** (substring) | did the pack surface the right LUZ keys, components, endpoints, repos? |

As built: `metrics/node_overlap.py::retrieval_scores(retrieved, relevant, hard_neg)` returns a typed
`RetrievalScore(precision, recall, leaked, missing)` — **precision/recall + the sorted `leaked` and `missing`
id lists** (no F1 field; the earlier design carried one, the shipped model dropped it as unused).
`metrics/entities.py::entities_recall` does the deterministic entity tier.

### 5.2 Generation metrics — score the understanding

| Metric | Definition | Kind | KGA mapping |
|---|---|---|---|
| **Faithfulness** | fraction of claims in the answer supported by the retrieved context | **Judge** (RAGAS) | is every statement in the understanding traceable to a pack note? Same intent as ADK `hallucinations_v1`. |
| **Response Relevancy** | does the answer directly address the question | **Judge** (RAGAS) | does the understanding address *this ticket's* AC, not a neighbour's? |
| `cites_only_real_ids` | every Jira key named in the understanding belongs to a pack node | **Det.** (regex + set) | fabrication guard (output level); shipped in `metrics/rubrics.py`. |
| `no_invented_urls` | every URL in the understanding also appears in the pack text | **Det.** (regex) | fabricated-link guard; shipped in `metrics/rubrics.py`. |
| `names_the_ac` / `declares_gaps_honestly` | semantic rubrics: real AC named, gaps acknowledged | **Judge** (semantic) | declared as data (`SEMANTIC_RUBRICS`), run through an injected `judge(q, text) -> bool`. |

The two fabrication rubrics are **deterministic and run at runtime** inside `evaluate_pack`; the two semantic
rubrics are **opt-in judged** (V2) — set on `EvalReport.semantic` only by `eval/judged.py`, never by the
default deterministic path (`report.semantic` stays `None` offline).

### 5.3 The composite — Pack Quality Score (PQS)

For dashboards, one weighted mean, weighting **groundedness and precision highest** because our real incidents
were bleed + hallucination, not missing recall (`metrics/pqs.py`):

```
PQS = 0.30·faithfulness + 0.25·ctx_precision + 0.20·ctx_recall
    + 0.15·relevancy + 0.10·trajectory
```

At **runtime** (`engine.py::evaluate_pack(bank, context_id, case=None)` — note: **no `trajectory=` kwarg**) the
`PQSComponents` are filled from the persisted pack:

- `faithfulness` = the two fabrication rubrics both passing (`cites_only_real_ids ∧ no_invented_urls`, as `0.0/1.0`);
- `ctx_precision` / `ctx_recall` from `node_overlap`;
- `relevancy` from `entities_recall`;
- `trajectory` = **fixed `1.0`** — the tier trajectory needs the gather reply, which only the offline harness
  and the ADK-native runner have, so the runtime agent leaves it neutral and the harness scores it separately.

**Always emit the components** next to the number: a 0.04 PQS drop could be all faithfulness or all recall, and
you need to know which surface regressed to act. This mirrors the HTML spec's rule — *score each dimension
separately; only some need the LLM judge; compute the rest deterministically.*

---

## 6. Layer 2 — Agent process · Google ADK Evaluation

Layer 2 scores the controller, not the pack. Since the ADK-native cutover the KGA **is** an ADK agent (a
`RouterAgent` = ADK `BaseAgent`, served via `to_a2a`), so we can use ADK's own eval harness directly — the
`eval/` subpackage (§10.2, Plan B) — as well as our deterministic trajectory metric.

> **Diagram:** Layer 2 in detail — [`kga-layer2-process-adk.excalidraw`](./kga-layer2-process-adk.excalidraw) · [`.png`](./kga-layer2-process-adk.png)

![Layer 2 (Agent process · Google ADK). Three sections. A: the trajectory being scored — the outer gather_knowledge → refine → approve sequence (in_order) plus the inner tier trace (in_order) and fetch-kind trace (any_order), with the trajectory_score(actual, expected, mode) code chip. B: the ADK metric catalog — tool_trajectory_avg_score=1.0, Tool Call Accuracy, Agent Goal Accuracy, response_match_score (det), hallucinations_v1 and final_response_match_v2 (judge), safety_v1 — each tagged det/judge. C: the ADK-native runner (Plan B) — golden/*.json → evalset.py → EvalSet/EvalCase → runner.py (AgentEvaluator) → EvalConfig criteria, with the EvalSet→EvalCase→Invocation data model and the PACK_METRICS / JUDGED_METRICS thresholds.](./kga-layer2-process-adk.png)

### 6.1 The data model

ADK structures eval as **EvalSet → EvalCase → Invocation**. An EvalCase records, for one seed, the user input,
the **expected tool-use trajectory**, and the **reference final response**. Author two ways: `adk eval` on a
saved `.evalset.json`, or `AgentEvaluator.evaluate()` inside `pytest`. Thresholds live in a separate
**EvalConfig** (`test_config.json`) so criteria can be tuned without touching cases. As built, `eval/evalset.py`
emits `kga_pack.evalset.json` + `tpd_plan.evalset.json` + `test_config.json` from the golden sets; the shipped
`TEST_CONFIG` criteria are `{"tool_trajectory_avg_score": 1.0, "response_match_score": 0.35}`.

### 6.2 The metric catalog (from `adk-python` `PrebuiltMetrics`)

| Config key | Measures | Judge | Applies to KGA? |
|---|---|---|---|
| `tool_trajectory_avg_score` | exact match of the tool-call sequence (EXACT / IN_ORDER / ANY_ORDER) | deterministic | **YES, high value** — the tier + fetch order; catches the dev-panel/parent regression |
| `response_match_score` | ROUGE-1 word overlap vs reference | deterministic | LIMITED — only the deterministic count line |
| `final_response_match_v2` | LLM-judged **semantic** match to the reference | LLM | YES for refine (paraphrastic; beats ROUGE) |
| `hallucinations_v1` | splits the response into sentences, checks each is grounded | LLM | **YES, critical** — the refine understanding groundedness (Layer-1 cross-check) |
| `rubric_based_final_response_quality_v1` | LLM-judged quality against custom rubrics | LLM | YES — our `SEMANTIC_RUBRICS` map onto it (§10.3) |
| `safety_v1` | harmlessness | LLM / Vertex | LOW — read-only over internal Atlassian; a cheap floor |

As built, `eval/config.py` declares the ADK criteria: `PACK_METRICS` = `pqs_score` (threshold 0.70, our PQS as
a custom metric) + `hard_negative_leak` (threshold 1.0, the bleed gate as a custom metric); the judged tier is
`JUDGED_METRICS = (hallucinations_v1, rubric_based_final_response_quality_v1, final_response_match_v2)` at
`JUDGED_THRESHOLD = 0.70`.

### 6.3 Deterministic trajectory + tool-use

Our own `metrics/trajectory.py::trajectory_score(actual, expected, mode)` (modes `exact` / `in_order` /
`any_order`) mirrors `tool_trajectory_avg_score` and scores two traces the offline harness derives from the
gather reply: the **tier trace** (which fan-out tiers fired, `in_order`) and the **fetch-kind trace** (node-kind
prefixes, `any_order`). This is the deterministic PR gate on the control flow — a reverted dev-panel fetch turns
it red. Agent Goal Accuracy (did the run end in an approved, on-domain pack?) is the Layer-2 binary label.

---

## 7. Layer 3 — Downstream effectiveness

A pack is an intermediate artifact; its real value is what it *enables* and what it *doesn't corrupt*. Layer 3
is the hardest to score directly, so it's a set of proxies today.

> **Diagram:** Layer 3 in detail — [`kga-layer3-downstream.excalidraw`](./kga-layer3-downstream.excalidraw) · [`.png`](./kga-layer3-downstream.png)

![Layer 3 (Downstream effectiveness), three dashed-green panels signalling "beyond the pack — a proxy, not folded into PQS". Panel 1, Noise Sensitivity: a causal bleed experiment — a clean path (gather+refine → understanding_A) vs a noisy path (inject the hard-negative jira:LUZ-799 into the seed's issuelinks → understanding_B), both feeding drift_score(A, B, injected_terms) → NoiseScore (0.0 = noise ignored). Panel 2, Topic Adherence: a declining adherence curve over explore-loop rounds with a cliff marker at round K ("cap the loop at K"), from adherence_curve(). Panel 3, the plan handoff: this pack → TPD define/implement → plan+suite → Test-Plan Score, with a dashed arrow crossing a "beyond the pack" boundary — a high-recall-but-bled pack is a Layer-1 pass and a Layer-3 fail.](./kga-layer3-downstream.png)

**1. Noise Sensitivity — does one irrelevant node corrupt the answer?** This is the **memory-bleed metric at
the output level.** Precision (Layer 1) catches the irrelevant ZIP-import node being *retrieved*; noise
sensitivity catches whether it actually *changed the understanding* — exactly the bleed incident.
`metrics/noise.py::drift_score(baseline, perturbed, injected_terms)` returns a typed `NoiseScore` — the
fraction of injected terms that surfaced in `perturbed` but not `baseline` (`0.0` = noise ignored). The
harness runs it as a **causal** experiment: gather+refine a clean pack, inject the hard-negative into the
seed's `issuelinks` so it enters a noisy pack, re-gather+refine, and measure the drift. Toggle a de-bias knob
and watch the injected terms stop leaking.

**2. Topic Adherence — does the explore loop stay on-seed?** The loop derives round-N focus from round N-1's
node titles, which can **drift** into the memory gravity well (a thin seed drifting to a 43-node wrong-domain
pack). `metrics/topic.py::adherence(round_terms, seed_terms)` scores the fraction of a round's focus terms
still on the seed's topic (deterministic token-overlap); `adherence_curve(rounds, seed_terms)` plots it per
round — a monotone decline is drift; a cliff at round K says cap the loop at K. The payoff: the loop knobs
become **tunable against a number** instead of by eye.

**3. The plan handoff — the truest downstream signal.** The pack exists to be turned into a test plan. Its
ultimate quality is the TPD plan built on it — scored by the sibling
[`RESEARCH-tpd-evaluation-adk-testsuite.md`](./RESEARCH-tpd-evaluation-adk-testsuite.md). A high-recall but
bled pack that produces a confidently-wrong plan is a Layer-1 pass and a Layer-3 failure; that is why the two
reports are one program. (Human-acceptance of the pack — kept vs edited vs discarded — is the other Layer-3
proxy, not yet instrumented.)

Layer 3 is **not** folded into the PQS number (it needs the downstream artifact), but its two shipped proxies
gate the explore loop and the bleed guard.

---

## 8. The mapping — KGA stage × metric × layer (core deliverable)

The table to implement against. "Det." = deterministic/cheap (PR gate). "Judge" = LLM-judged (nightly).

| KGA stage / artifact | Layer | Primary metric(s) | Framework | Kind | Ground truth |
|---|---|---|---|---|---|
| Outer tool sequence `gather→refine→approve` | 2 | `tool_trajectory_avg_score` (IN_ORDER) | ADK | Det. | expected tool list |
| Inner tier order | 2 | trajectory + Tool Call Accuracy | ADK/RAGAS | Det. | expected tier list per seed shape |
| Crawl fetch calls (dev-panel, remote-links) | 2 | Tool Call Accuracy | RAGAS | Det. | expected fetch kinds |
| **Memory retriever** node set | 1 | Context Precision / Recall + hard-neg gate | RAGAS | Det. | golden relevant-id set |
| Memory retriever entity coverage | 1 | Context Entities Recall | RAGAS | Det. | golden entity list |
| **Combined pack** node set | 1 | Context Precision / Recall | RAGAS | Det. | golden relevant-id set |
| **Refine understanding** groundedness | 1 | Faithfulness / `hallucinations_v1` / `cites_only_real_ids` | RAGAS/ADK | Judge + Det. | — |
| Refine understanding correctness | 1 | `final_response_match_v2` | ADK | Judge | reference understanding |
| Refine understanding on-task | 1 | Response Relevancy | RAGAS | Judge | — |
| `summarize_gather` count line | 2 | `response_match_score` (ROUGE) | ADK | Det. | expected counts |
| Bleed at the output level | 3 | **Noise Sensitivity** (causal) | RAGAS | Det. | hard-negative terms |
| Explore-loop rounds | 3 | **Topic Adherence** curve | RAGAS | Det. | seed topic ref |
| The plan built on the pack | 3 | TPS (sibling report) | testing | Judge | golden plan |
| Whole run | 2 | Agent Goal Accuracy (approved, on-domain) | RAGAS | Judge | binary label |

---

## 9. The golden dataset (evalset) design

The harness is only as good as the golden set. Curate **8–15 seeds** spanning the shapes that break the KGA:

| Seed shape | Example | Why it's in the set | Role |
|---|---|---|---|
| Rich, well-linked ticket | LUZ-158390 | happy path; high recall expected | must-pass |
| **Thin container** (title only) | LUZ-159312 | the 0-links false-negative; tests parent climb | **canary** (low recall if regressed) |
| **Bleed-prone** billing seed | luz_finance ticket | tests precision vs the ZIP-import well | **canary** (must not leak) |
| Ticket with dev-panel repo | any with PRs | tests codegraph + Tool Call Accuracy | must-pass |
| Confluence page seed | a spec page | non-Jira retrieval | must-pass |
| Cross-domain umbrella | epic w/ subtasks | recall + focus tension | must-pass |

Per seed, author a small JSON (the shipped `EvalCase` dataclass in `models.py`) with the **minimum viable
ground truth**:

```json
{
  "seed": "eval_thin",
  "fixture": "eval_thin",
  "shape": "thin-container",
  "expected_trajectory": ["gather_knowledge", "refine", "approve"],
  "expected_tiers": ["B1_climb", "G1_atlassian_search", "crawl"],
  "expected_fetch_kinds": ["jira", "confluence"],
  "relevant_node_ids": ["jira:LUZ-156281", "jira:LUZ-159312", "codegraph:axonivy-prod/luz_finance"],
  "must_not_retrieve_ids": ["jira:LUZ-158390", "codegraph:epost/zip-import"],
  "key_entities": ["luz_finance", "invoice", "charge", "LUZ-156281"],
  "min_recall": 0.8,
  "min_precision": 0.7,
  "reference_understanding": "This ticket adds … The AC requires … Grounded in luz_finance …"
}
```

Mapping to the metrics (and to the HTML golden-schema vocabulary):

- `relevant_node_ids` → Context Recall/Precision by set overlap. These are the **must-have** cases in the HTML
  schema; a *nice-to-have* split (softer recall targets) is a natural refinement — today all listed ids are
  must-have and the `min_recall` field is the single softness knob.
- `must_not_retrieve_ids` → the **hard-negative** list = the HTML schema's **known_traps**. Every hallucination
  or bleed pattern found in production becomes a hard-negative entry here; *any* appearance is a hard fail.
- `key_entities` → Context Entities Recall.
- `reference_understanding` → `final_response_match_v2` / Faithfulness anchor.

Golden seeds live in [`src/test_evaluation/golden/*.json`](../src/test_evaluation/golden/) (loaded by
`golden.py`); the recorded Atlassian fixtures live alongside the harness in `tests/eval/fixtures/atlassian/`.
Both are in git — they are the spec of "good". **As built, the seeds are the synthetic
`eval_rich`/`eval_bleed`/`eval_thin` cases** (the last two double as canaries); §9's live LUZ-keyed 8–15 set is
the pending coverage work.

---

## 10. Engine + harness design — **as built**

**Offline, deterministic-first, LLM-judged-nightly** — mirroring the codebase's discipline (blocking LLM calls
are `asyncio.to_thread`-offloaded; expensive tiers earn their cost). The build has **three** pieces: a
deployable **scoring engine**, a test-side **offline harness**, and an **ADK-native runner** unlocked by the
cutover. Appendix A carries the full file-by-file layout; this section is the shape and rationale.

### 10.1 The scoring engine — `src/test_evaluation/` (the ADK-native third agent)

The engine that turns a persisted pack into a score is a **first-class agent**, peer to `knowledge_gathering` /
`test_plan_definition` / `admin_agent` — not a test fixture. That is what lets the same code run as a required
PR check *and* an optional runtime quality gate the pipeline calls after `approve`.

```
src/test_evaluation/
  models.py            # every metric result a typed dataclass (no bare dicts cross module boundaries)
  metrics/             # trajectory · node_overlap · entities · noise · topic · ragas_judge · pqs · rubrics · history
                       #  + coverage · oracle · mutation · placeholders · gherkin_lint · tps   (the TPD half)
  golden.py  golden/*.json         # the §9 KGA EvalCases (eval_rich / eval_bleed / eval_thin)
  golden_plans/*.json              # the TPD PlanEvalCases (sibling report)
  engine.py            # evaluate_pack(bank, context_id, case) -> EvalReport   (deterministic, no LLM/net)
  plan_engine.py       # evaluate_plan(...) -> PlanReport                        (the TPD scorer)
  agent.py             # EvaluatorAgent(RouterAgent) — ADK-native router (evaluate_pack | evaluate_plan)
  ops.py               # framework-neutral parse + report rendering (was executor/base.py, C2)
  bridge/mcp_server.py # register_tools(mcp, session) -> {evaluate_pack, evaluate_plan}  (on the ONE gateway)
  eval/                # the ADK-native runner (Plan B) — see §10.2
  monitoring.py        # a TEV-namespaced LoggingToggle
```

`engine.py::evaluate_pack` reads the **run-scoped** pack exactly as refine does
(`common.interrogate.pack.load_pack(bank, context_id)`) plus the restated understanding
(`bank.read_understanding`), and scores retrieval (node-overlap + hard-negative leak gate), entity coverage,
and the fabrication rubrics into a PQS — **without importing the other agents**.

> **What changed since the first design.** The engine used to sketch an `executor/` + `server.py` + a per-agent
> MCP bridge sidecar. After the ADK-native cutover: `agent.py` is a deterministic `RouterAgent` (ADK
> `BaseAgent`) whose `_run_async_impl` routes `"…plan…"` → `evaluate_plan`, else `evaluate_pack`, each run in a
> worker thread (`asyncio.to_thread`); the old `executor/base.py` parse/render helpers are now
> framework-neutral `ops.py`; there is **no `server.py`** — serving is the shared root `main:app`
> (`common.adk.serve.build_agent_app`, `AGENT=test_evaluation`, `to_a2a` + durable task store + bearer +
> health); and the MCP tools register on the **single `gateway` service**, not a sidecar.

### 10.2 Two harness paths — the custom offline harness *and* the ADK-native runner

**(a) The offline harness — `tests/eval/` (drives the *real* KGA).** Scoring a pack tells you nothing unless
you can **produce** one deterministically. That job — driving a real gather/refine offline — lives test-side,
because it imports `knowledge_gathering` and must not pollute `test_evaluation`'s cross-agent independence.

```
tests/eval/
  harness.py                 # run_gather_offline / run_refine_offline + RunTrace + RecordedAtlassianClient
  harness_tpd.py             # the TPD driver (sibling report)
  fixtures/atlassian/*.json  # recorded Jira/Confluence responses, one per golden seed
  test_metrics.py  test_eval_deterministic.py  test_engine.py  test_eval_judged.py
  test_eval_tpd_deterministic.py  test_eval_tpd_metrics.py  test_plan_engine.py  test_eval_tpd_judged.py
  test_judge.py  test_adk_eval.py …
```

The harness drives the KGA over the **same in-process A2A stack the wiring tests use** (a Starlette
`TestClient` posting JSON-RPC `message/send`) with a `RecordedAtlassianClient` (fixture-backed; it **records
every call** for tool-use trajectory) and a `FakeBucket`-backed `MemoryBank`. So a gather runs the *actual*
crawl + fan-out but touches nothing external. Each run yields a `RunTrace` exposing what a human reviews:
`reply`, `node_ids`/`node_texts`, `tiers`, `fetch_kinds`, `tool_calls`, `understanding`. **Reuse
`trace.context_id` for refine** — the crawl stamps every note with `run_id == context_id`, so a fresh id sees
nothing.

**(b) The ADK-native runner — `src/test_evaluation/eval/` (Plan B).** The cutover made the agents real ADK
agents, so ADK's own eval harness now applies. This subpackage wires our domain scores into ADK:

- `eval/adk_metrics.py` — our engines exposed as ADK **custom-metric functions**: `pqs_score`,
  `hard_negative_leak`, `tps_score`, `must_not_scope_leak` (each returns an ADK `EvaluationResult`). `set_bank`
  injects the bank for tests.
- `eval/config.py` — the ADK criteria: `PACK_METRICS` / `PLAN_METRICS` (custom-function paths + thresholds)
  and `judged_criteria()` — the LLM-judged tier as an `EvalConfig.criteria` map (hallucinations + rubric-based
  quality with our `SEMANTIC_RUBRICS` + final-response-match), **returning `{}` (a clean skip) when the
  provider is unconfigured**.
- `eval/evalset.py` — golden JSON → ADK `EvalSet`/`EvalCase`, and `write_eval_data()` emits the on-disk
  `eval/data/{kga_pack,tpd_plan}.evalset.json` + `test_config.json`.
- `eval/runner.py` — the canonical `AgentEvaluator` harness (`run_agent_eval`) + the judged tier
  (`run_judged_eval`, double-gated on creds **and** a provider-sourced judge model).

### 10.3 The provider-sourced judge (I8) — Claude-on-Vertex, never a vendor default

Every LLM-judged path in the eval agent sources its model from the **one configured `ModelProvider`**
(`agent_model()` / `VertexClaudeProvider`), never RAGAS's OpenAI default or ADK's Gemini default. This is
enforced, not conventional:

- `metrics/ragas_judge.py::judge` **raises `ValueError` up front** if `llm` or `embeddings` is `None` — it
  refuses to let RAGAS fall back to OpenAI.
- `eval/judge.py` builds the RAGAS LLM/embeddings and the semantic `judge(q, text) -> bool` from the provider
  (Claude-on-Vertex via `ChatLiteLLM` / Vertex embeddings), and every factory returns **`None` — a clean
  skip** — when the `[eval]` extra or `VERTEX_*` creds are absent.
- `eval/config.py::judged_criteria` and `eval/runner.py::run_judged_eval` pull the judge model id from the
  provider and skip when it is `None`.

So the offline suite touches no network, and when the judged tier *does* run, the judge is a pinned,
provider-sourced model — which is exactly what the calibration protocol (§11) needs.

### 10.4 Three lanes of run

1. **PR gate (seconds, no LLM, no network).** Replay each golden seed through the offline harness and score
   trajectory + node-overlap + entities + fabrication rubrics + PQS. `pytest tests/eval/test_metrics.py
   tests/eval/test_eval_deterministic.py tests/eval/test_engine.py` (plus the TPD siblings) is the required
   check — gate on a clean working tree so an eval pass can't mask an uncommitted edit.
2. **Nightly / `eval:` label (minutes, LLM).** `test_eval_judged.py` adds RAGAS faithfulness / response
   relevancy over the understanding and the semantic rubrics; these **skip cleanly** without the `[eval]` extra
   (`ragas_judge.available()`) or a provider. Post the **PQS + component deltas** vs the last main-branch
   baseline.
3. **ADK-native runner (creds only).** `eval/runner.py` drives ADK's own `AgentEvaluator` over the emitted
   evalsets — the trajectory + judged criteria path. Also creds-gated; a superset second opinion to the custom
   harness.

**Determinism & flakiness.** LLM-judged metrics vary run-to-run — sample `num_samples≥3`, compare **means**,
and gate on a **delta band** ("faithfulness dropped >0.05 vs baseline"), never an absolute pass/fail on one
sample. Deterministic metrics gate absolutely; that is why the required check carries only them.

---

## 11. Judge calibration & canary seeds

The LLM-judged tier (Faithfulness, `hallucinations_v1`, the semantic rubrics) is trustworthy only once the
provider-sourced judge is **calibrated against humans**, and the deliberately-bad **canary seeds**
(`golden/canary/`) are the cheap drift guard between recalibrations. The full protocol — Cohen's kappa, the
`judge-human kappa >= human-human kappa - 0.1` gate, why a low human-human kappa is a rubric-wording bug (fix
the rubric, not the judge), and the shipped canary implementation — is its own page:
**[`RESEARCH-judge-calibration-kappa.md`](./RESEARCH-judge-calibration-kappa.md)**.

In short: keep a dimension **judged** only if the judge agrees with a human about as well as two humans agree
with each other; otherwise keep it **deterministic** (which is why most of the PQS is set-overlap + regex). Pin
the judge model (`judge_model_id()`) and re-calibrate on any model/prompt change.

## 12. What the metrics would have caught (retro-fit to real incidents)

Each past KGA incident maps to a metric that would have flagged it **before** a human noticed — the strongest
argument for building this:

| Incident (memory note) | Layer | Metric that flags it | How |
|---|---|---|---|
| **memory-bleed → wrong ticket** | 1 + 3 | Context Precision ↓, hard-neg leak, Noise Sensitivity ↑, Faithfulness ↓ | the billing seed's `must_not_retrieve_ids` lists the ZIP-import nodes; any appearance fails the gate, and the drifted understanding fails faithfulness + noise. |
| **0-links false-negative** (thin → 1 node) | 1 | Context Recall ↓ | the thin seed's `relevant_node_ids` has the parent + siblings; a 1-node crawl scores near-zero recall. |
| **crawler misses parent + dev panel** | 2 | `tool_trajectory_avg_score` ↓, Tool Call Accuracy ↓ | expected trajectory includes the dev-status + parent fetch; dropping them fails the order match. |
| **interrogation asks nothing** ("high confidence") | 2 | Agent Goal Accuracy = 0, Response Relevancy ↓ | an empty interrogation on a rich seed = goal not achieved; the "understanding" is generic. |
| **ungrounded lead promoted** | 1 | Faithfulness ↓, `cites_only_real_ids` fail | an ungrounded lead introduces unsupported claims / invented ids in the understanding. |
| **explore-loop drift** | 3 | Topic Adherence ↓ | round-over-round focus compared to the seed topic reference. |

---

## 13. Phased roadmap — **shipped**

Cheap, deterministic value first; expensive LLM judging last — the "earn-the-cost" pattern the agents follow.
All phases landed (Appendix A is the file-by-file record); the remaining work is **coverage** (§9's 8–15 live
seeds) and E4's render/alert tail, not machinery.

- **E0 — Golden set + trajectory (no LLM). ✅** 3 golden seeds; `metrics/trajectory.py` scores the tier +
  fetch-kind sequences as a **required PR check** (Layer 2).
- **E1 — Node-overlap retrieval scores (no LLM). ✅** `metrics/node_overlap.py` gives Context Precision/Recall
  by id-set overlap + the hard-negative leak gate — catches bleed **and** the 0-links case (Layer 1).
- **E2 — Groundedness judging (LLM, nightly). ✅ gated.** `metrics/ragas_judge.py` scores RAGAS Faithfulness +
  Response Relevancy over the understanding; **provider-sourced**, skips without the `[eval]` extra (Layer 1).
- **E3 — Entity recall + noise + topic adherence. ✅ deterministic.** `metrics/entities.py`, `metrics/noise.py`
  (counterfactual drift), `metrics/topic.py` — the explore loop is tunable against a drift number (Layers 1+3).
- **E4 — Rubrics + PQS + history (ongoing). ◑** PQS (`pqs.py`), the two deterministic fabrication rubrics +
  declared semantic rubrics (`rubrics.py`), and the append-only history primitive (`history.py`) shipped; the
  render + main-branch-regression alert tail remains.
- **E5 — ADK-native runner (Plan B). ✅** the cutover unlocked ADK's own harness: `eval/` wires our scores as
  ADK custom metrics (`adk_metrics.py`/`config.py`), emits evalsets (`evalset.py`), and drives `AgentEvaluator`
  (`runner.py`) with a provider-sourced judged tier.

---

## 14. Constraints & gotchas (from this system's own history)

- **Cloud Run timeout is the hard ceiling — which is why the runtime engine is deterministic-only.** Never run
  **LLM-judged** eval inside the agent request path — an event-loop-blocking Vertex call already killed an
  instance (`ERROR_TIMEOUT`). The runtime `evaluate_pack` scores a pack **inside** a request, but *only the
  deterministic metrics*, and even those run in a worker thread (`asyncio.to_thread`). The LLM-judged tier
  stays **out of band** — pytest/CI + the offline harness + the ADK runner, never in the router.
- **The judge is provider-sourced, and that is enforced.** `ragas_judge.judge` raises on a `None` llm rather
  than silently using OpenAI; `judged_criteria()` returns `{}` without a provider. A judged run with no
  `VERTEX_*` creds is a clean skip, not a wrong-vendor result.
- **GCS memory state is shared and mutable.** A gather **writes** the index; the harness uses a temp/isolated
  `FakeBucket` bank and recorded fixtures — never the prod `GCS_BUCKET` (a redeploy has silently wiped state).
- **The working tree, not the commit, is what runs.** `gcloud builds submit` and pytest both use the working
  tree — gate on a clean tree so an eval pass can't mask an inconsistent commit.
- **`tool_trajectory_avg_score` default 1.0 is only valid on deterministic stages.** The LLM planner tiers and
  the distiller are stochastic — assert trajectory on the deterministic skeleton (crawl fetch order, tier
  presence), not on stochastic sub-steps. The runtime PQS leaves `trajectory` neutral (1.0) for the same reason.
- **RAGAS/ADK assume one retriever.** The KGA has two (crawl + memory) — score them separately *and* combined,
  or the memory-bleed signal gets averaged away.
- **`.env` leaks VERTEX into offline tests.** Agent `__init__` `load_dotenv()` pulls local `VERTEX_*` into the
  environment at pytest collection, which would make the "no-LLM" paths hit real Vertex and hang. A
  session-scoped autouse fixture clears them; keep the judged tier explicitly opt-in.

---

## 15. Sources

Primary (preferred):
- [Google ADK — Why evaluate agents](https://google.github.io/adk-docs/evaluate/) · [Evaluation criteria reference](https://adk.dev/evaluate/criteria/)
- [`adk-python` `eval_metrics.py` (PrebuiltMetrics enum)](https://github.com/google/adk-python/blob/main/src/google/adk/evaluation/eval_metrics.py)
- [RAGAS — List of available metrics](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/) · [Agentic / tool-use metrics](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/agents/)
- The three-layer framework, golden-schema, weighted-rubric and calibration protocol: the local
  [`agentic-qa-eval-framework.html`](./agentic-qa-eval-framework.html) evaluation spec.

Secondary / corroborating (blogs — treated as *unverified* where they exceed the primary docs):
- [Testing with ADK — Agent evaluations (Google Cloud, Medium)](https://medium.com/google-cloud/testing-with-agent-development-kit-agent-evaluations-76a9eec27965)
- [Evaluate Amazon Bedrock Agents with Ragas (AWS)](https://aws.amazon.com/blogs/machine-learning/evaluate-amazon-bedrock-agents-with-ragas-and-llm-as-a-judge/)

*Cross-check status: ADK metric names + EvalConfig schema corroborated against the `adk-python` source and the
official criteria docs. RAGAS metric names + categories corroborated against the official `docs.ragas.io` metric
index. Treat exact judge-model defaults as version-dependent — this system pins its own provider-sourced judge
(§10.3) rather than relying on any vendor default.*

---

## Appendix A — Implementation plan (phase by phase) — **as built**

> **This appendix is the as-built record, not a forward plan.** The §13 roadmap (E0–E5) shipped. The engine is
> a **first-class, ADK-native, deployable agent** — `src/test_evaluation/` — and the code is split across two
> locations:
> - the scoring **engine + ADK runner** — **`src/test_evaluation/`** — peer to the other agents, deployed as
>   its own Cloud Run service and reachable at runtime via the `evaluate_pack` / `evaluate_plan` MCP tools on
>   the single gateway;
> - the offline **harness + tests** — **`tests/eval/`** — the harness imports `knowledge_gathering` /
>   `test_plan_definition` to drive a *real* run, so it stays test-side to keep `test_evaluation` free of
>   cross-agent deps.
>
> Deterministic phases (E0–E1, the deterministic parts of E3/E4) are required PR checks; the E2 RAGAS tier +
> E5 ADK judged runner are creds/extra-gated and **skip** cleanly.

### Layout (as built)

```
src/test_evaluation/               # the deployed, ADK-native eval agent — scores a PERSISTED artifact
  models.py                        # every metric result a typed dataclass (no bare dicts cross modules)
  metrics/
    trajectory.py   node_overlap.py   entities.py   noise.py   topic.py
    ragas_judge.py  pqs.py            rubrics.py     history.py            # the KGA (pack) half
    coverage.py     oracle.py         mutation.py    placeholders.py       # the TPD (plan) half
    gherkin_lint.py tps.py                                                 #  (sibling report)
  golden.py  golden/*.json          # eval_rich · eval_bleed · eval_thin  (3 KGA seeds; §9's 8–15 pending)
  golden_plans/*.json               # plan_rich · plan_bleed · plan_thin  (TPD seeds)
  engine.py                         # evaluate_pack(bank, context_id, case) -> EvalReport
  plan_engine.py                    # evaluate_plan(bank, context_id, case, *, detail) -> PlanReport
  agent.py                          # EvaluatorAgent(RouterAgent): routes pack | plan; asyncio.to_thread
  ops.py                            # extract_ctx / _is_plan / render / render_plan (framework-neutral)
  bridge/mcp_server.py              # register_tools -> {evaluate_pack, evaluate_plan}  (on gateway.mcp_server)
  eval/                             # ADK-native runner (Plan B)
    adk_metrics.py  config.py  evalset.py  judge.py  judged.py  runner.py
    data/{kga_pack,tpd_plan}.evalset.json  data/test_config.json
  monitoring.py                     # TEV-namespaced LoggingToggle

tests/eval/                        # out-of-band harness + tests (never in the agent request path)
  harness.py  harness_tpd.py        # run_*_offline + RunTrace + RecordedAtlassianClient
  fixtures/atlassian/*.json         # recorded Jira/Confluence responses
  test_metrics.py                   # E0/E1 metric math (PR gate)
  test_eval_deterministic.py        # E0 trajectory + E1 node-overlap, seed-driven (PR gate)
  test_engine.py                    # evaluate_pack + the ADK router, end-to-end (PR gate)
  test_eval_judged.py               # E2 RAGAS · E3 entity/noise/topic · E4 PQS/rubrics/history (nightly)
  test_judge.py  test_adk_eval.py test_adk_eval_files.py   # E5 provider-sourced judge + ADK runner + evalsets
  README.md
```

### The runtime + deployment surface — **the change from the original plan**

The original Appendix A stopped at a `tests/eval/` harness and sketched a bespoke A2A `executor/` + `server.py`.
The build went further and then the ADK-native cutover simplified it:

- **`engine.py::evaluate_pack(bank, context_id, case=None) -> EvalReport`** — reads the run-scoped pack the way
  refine does + the restated understanding, scores retrieval + entities + fabrication rubrics, composes the
  PQS. Fully deterministic — no network, no LLM. `trajectory` stays neutral (1.0) at runtime.
- **`agent.py` — `EvaluatorAgent(RouterAgent)`** — the ADK-native router (not an A2A executor). `_run_async_impl`
  reads the turn text, resolves the context id (`ops.extract_ctx` or the session id), and routes
  `evaluate_plan` (text contains "plan") else `evaluate_pack`, each in a worker thread; renders via
  `ops.render` / `ops.render_plan`. Read-only over the shared bank; never imports the other agents.
- **Serving** — there is **no `server.py`**. The container runs the shared root `main:app`
  (`common.adk.serve.build_agent_app`) with `AGENT=test_evaluation` — ADK `to_a2a` routes, the durable Cloud
  SQL / in-memory task store, `BearerAuthMiddleware`, and health probes (needs only `GCS_BUCKET`, no Atlassian).
- **`bridge/mcp_server.py`** — registers `evaluate_pack(context_id)` + `evaluate_plan(context_id)` on the
  **single `testing-agent-gateway`** MCP server (`src/gateway/mcp_server.py`), which fronts all four A2A agents
  over one endpoint. There is no per-agent bridge sidecar.
- **Deployment** — terraform `module.tev` in `deployments/test-agent-v2/services.tf`, gated by
  `var.deploy_test_evaluation`, running `uvicorn main:app` with `AGENT=test_evaluation`. The gateway service
  reaches it via `TEV_A2A_URL` (`module.tev.uri`). `admin_agent` is the fourth service (memory/history
  operator utility, `module.admin`), not part of the gather→…→implement pipeline.

**Pipeline integration.** In the Testing-Agent flow (`common/bridge/prompts.py`), evaluation is an **optional,
read-only, never-blocking** gate: after `approve`, if `test-evaluation` is connected, call
`evaluate_pack(context_id)` and surface the PQS + retrieval/rubric breakdown; on a hard-negative leak or low
recall, offer to re-gather before planning. (`evaluate_plan` is the same gate after `implement_plan`.)

### Sequencing & effort — **as built**

| Phase | Depends on | LLM? | Gate | Status |
|---|---|---|---|---|
| E0 trajectory | — | no | PR-required | **done** |
| E1 node-overlap | E0 scaffolding | no | PR-required | **done** |
| E2 RAGAS faithfulness/relevancy | E0 + refine driver | yes (provider-sourced) | nightly / `eval:` | **done, skips without `[eval]`/creds** |
| E3 entities · noise · topic | E2 driver | no (deterministic core) | nightly, always-run | **done** |
| E4 PQS · rubrics · history | E2/E3 scores | partial (LLM semantic rubrics) | dashboard | **PQS/det-rubrics/history done; render+alert pending** |
| E5 ADK-native runner | cutover + E0–E4 | yes (judged tier) | creds-gated | **done** |
| Runtime agent + deploy | E0–E4 engine | no | Cloud Run `module.tev` + pipeline gate | **done** |

The remaining work is **coverage, not machinery**: §9's 8–15 live-recorded golden seeds (only the 3 synthetic
`eval_*` seeds ship today), and E4's render/alert dashboard tail.
