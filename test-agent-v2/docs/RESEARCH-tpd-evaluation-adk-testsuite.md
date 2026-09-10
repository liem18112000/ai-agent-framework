# Evaluating the Test-Plan-Definition Agent — Google ADK metrics + test-suite adequacy

**Purpose.** The sibling report [`RESEARCH-kga-evaluation-adk-ragas.md`](./RESEARCH-kga-evaluation-adk-ragas.md)
answers *"given a seed ticket, how do we know the **pack** the KGA assembled is good?"* This one is its
downstream twin: *given an approved insight pack, how do we know the **test plan** the second agent — the
**Test-Plan-Definition Agent (TPD)** — defined and implemented is good?* Same goal, different artifact. Every
future change to the TPD (the define interrogation, the coverage matrix, the Claude-on-Vertex scenario/step
generators, the M6 prose brief, the L3/L4 self-learning hooks) should be judged against a **repeatable score**
instead of a hand-wave — so a regression is caught by a number, not by a human eyeballing a `.feature` file.

It draws on two established evaluation lenses and maps each, metric by metric, onto the TPD's actual code
paths (`define/loop.py`, `define/plan.py`, `implement/scenarios.py`, `implement/steps.py`,
`implement/testdata.py`, `render/gherkin.py`):

1. **Google ADK Evaluation** — the same agent-eval harness the KGA report adopts, reused here because the TPD
   is *also* a tool-using A2A agent. ADK scores two things a controller does: the **trajectory** (which tools
   it called, in what order — `define_plan → approve_plan → implement_plan`, and the inner
   `methodology → scope → metrics` round order) and the **final response** (is the plan brief correct,
   grounded, safe). This is the right lens for the TPD's *agentic control flow and groundedness*. RAGAS's
   **generation** metrics (Faithfulness, Response Relevancy) fold in here as the same-intent cross-check for
   "is the plan brief grounded in the pack?".
2. **Test-suite adequacy & quality** — the body of software-testing science that already answers *"is this a
   good test suite?"*: **coverage adequacy** (requirements/AC traceability, equivalence-partition + boundary
   coverage — ISTQB / ISO-IEC-IEEE 29119), **fault-detection adequacy** (mutation score — Jia & Harman;
   PIT/pitest on the JVM), **oracle strength** (does a scenario assert an end-state or just a status code?),
   and **BDD/Gherkin quality** (declarative-not-imperative, one-behaviour-per-scenario). This is the lens the
   KGA report did *not* need — the KGA is a retrieval system, the TPD is a **test-design** system — and it is
   the heart of this report.

> **Diagram (open in Excalidraw, PNG renders inline):**
> - The TPD measurement plane — [`tpd-evaluation-adk-testsuite.excalidraw`](./tpd-evaluation-adk-testsuite.excalidraw) · [`.png`](./tpd-evaluation-adk-testsuite.png)

> ⚠️ **Honesty note.** (1) The TPD is **not built on ADK** — it is a custom A2A agent (`a2a` server +
> `common.bridge` MCP), exactly like the KGA. We adopt ADK's **metric definitions and methodology**, not its
> runner, and port them into the same offline harness. (2) The deepest metric here — **mutation score /
> real fault detection** — needs the scenarios to actually *run* against the system under test. That
> execution stage does **not exist yet**; it is Pillar 2 ("Real Test Execution + Self-Healing") of
> [`RESEARCH-test-executor-agent.md`](./RESEARCH-test-executor-agent.md). Until it ships, fault
> detection is measured by a **deterministic proxy** (fault-class coverage + oracle strength), and the
> report says so at every step. (3) Where a claim comes from a single vendor blog rather than a primary
> standard, it is marked *(unverified)*.

> ✅ **Status (2026-09-05): IMPLEMENTED into the existing third agent.** The TPD scorer shipped as a second
> engine inside [`src/test_evaluation/`](../src/test_evaluation/) — **`plan_engine.py::evaluate_plan(bank,
> context_id, case) -> PlanReport`**, peer to `evaluate_pack`. New deterministic metrics (`metrics/coverage.py`,
> `oracle.py`, `placeholders.py`, `gherkin_lint.py`, `mutation.py` = fault-class proxy, `tps.py`) plus **reuse**
> of the shipped `node_overlap.retrieval_scores` for scope, `rubrics` for the brief, and `ragas_judge`/`history`/
> `trajectory`; new typed models (`PlanEvalCase`, `CoverageScore`, `OracleScore`, `PlaceholderReport`,
> `GherkinReport`, `FaultClassScore`, `TPSComponents`/`TPSResult`, `PlanReport`) added to `models.py`
> (scope reuses `RetrievalScore`). 3 golden plans (`golden_plans/plan_{rich,bleed,thin}.json`), the
> `evaluate_plan` MCP tool + A2A skill, and a test-side harness (`tests/eval/harness_tpd.py`) driving the real
> `gather → refine → define → implement` in-process. Suite **292 → 327 pass** (T2 RAGAS skips without the
> `[eval]` extra). Still design-only where it says so below: the LLM tiers (RAGAS brief faithfulness, LLM
> oracle/execution-depth) are wired but gated, and the mutation lane (T4) stays blocked on the execution stage
> (Pillar 2) — only the fault-class **proxy** ships. `test_evaluation` still **never imports
> `test_plan_definition`**: `evaluate_plan` reads the persisted plan/suite as plain JSON via the bank.

---

## 0. TL;DR — the one gap and the one principle

**Where we are.** The TPD has **zero automated quality evaluation of the plan it produces.** There are unit
tests for wiring (`tests/`), but nothing scores *the plan a define produces* or *the suite an implement
produces*. Regressions are caught only by a human comparing artifacts by hand — which is exactly how every
real TPD defect was found:

- the **define brief that ignores both the answers and the pack** (it auto-scoped LUZ-159312 to the
  *excluded* nodes and said "nothing out of scope" — the inverse of the approved understanding);
- the **silent heuristic fallback** that shipped 3 of 6+ behaviours when the LLM JSON truncated (looked full,
  was half-empty);
- the **execution-depth gap** — a codegraph-grounded plan with real *structure* but placeholder oracles,
  benchmarked against a human-authored, *executed* plan (~83 cases, real endpoints/states) that was far
  stronger;
- the **empty interrogation** ("high confidence", 0 questions) on a rich pack.

Every one is a **quality** failure a metric would have caught; none is a crash a unit test catches.

**The gap.** We cannot answer *"did this change make the plan better or worse?"* There is no golden set of
pack→reference-plan pairs, no coverage score, no traceability check, no fault-detection number. Every tuning
decision on `_MAX_NOTES`, `_STEP_BATCH`, `max_tokens`, the coverage matrix, or the prose brief is currently
**flown blind**.

**The principle.**

> **Grade the plan by what it would catch, not by how much it produced.** A test-plan agent is a *judgement*
> engine (the brief: methodology / scope / pass-criteria) feeding a *generative* engine (the scenarios /
> steps / test-data). A big suite that misses the real failure modes is worse than a small one that catches
> them — so score **coverage of behaviours and faults**, not scenario count. Measure four surfaces: (a) did
> the controller run the right `define→approve→implement` path and the right interrogation rounds (**ADK
> trajectory**); (b) is the brief grounded in and on-task for the approved pack — no invented scope, no
> excluded nodes (**groundedness / faithfulness**); (c) does the scenario set *cover* every in-scope
> behaviour and its negative / boundary / error partitions with real traceability to the ACs (**coverage
> adequacy**); and (d) would a scenario actually *catch a regression* — a real end-state oracle, not
> `assert 200` (**fault-detection / oracle strength**). Anchor every score to a small human-curated golden
> set of pack → reference-plan pairs — and where one exists, to a **human-authored, executed** plan as the
> ground truth.

**The shape of the answer.** One `.planeval.json` per pack (mirroring ADK's EvalCase), a metric-per-stage
matrix, and a `pytest`-driven offline harness with the same two lanes the KGA harness uses — a deterministic
PR gate on every commit, the expensive LLM-judged metrics nightly — plus a **third lane** (real mutation)
that unlocks only once the execution stage exists.

| Surface | Question | Lens | Headline metric |
|---|---|---|---|
| **Controller** | right tools + rounds, right order? | ADK | `tool_trajectory_avg_score` |
| **Brief groundedness** | scope/criteria true to the pack? | ADK + RAGAS | `hallucinations_v1` · Faithfulness · **Scope Precision/Recall** |
| **Coverage adequacy** | every behaviour + partition covered, traced to ACs? | test-suite science | **AC-Coverage Recall** · **Coverage-Matrix Completeness** · Traceability |
| **Fault detection** | would the tests catch a bug? | test-suite science | **Mutation Score** (later) · **Oracle Strength** + fault-class coverage (proxy now) |
| **Regression** | did this PR make it worse? | all | golden-set deltas in CI |

![The TPD measurement plane. Bottom: the TPD pipeline (Insight PACK → DEFINE Stage-A methodology·scope·metrics rounds → approve → TestPlan BRIEF → IMPLEMENT Stage-B coverage matrix → Scenarios/Steps + Test-data → .feature Gherkin export). Above it, four measurement panels each score the stage below via a dashed "measures" arrow: ① ADK trajectory/tool-use over the define→approve→implement flow and round order; ② brief groundedness (Faithfulness / hallucinations_v1 + Scope Precision/Recall with a must_not_scope hard-negative gate) over the TestPlan brief; ③ coverage adequacy (AC-Coverage Recall + Coverage-Matrix Completeness + Traceability) over the scenarios; ④ fault detection (Oracle Strength + fault-class coverage now, Mutation Score gated on the execution stage) over the suite. A single human-curated golden set — anchored to a REAL executed plan (LUZ-156281) — is the ground truth for every metric. The four score families combine into one weighted Test-Plan Score (TPS), consumed by a harness with three lanes: a deterministic PR gate (T0–T1), an LLM-judged nightly run (T2–T3), and a mutation lane (T4) that is blocked on the execution stage.](./tpd-evaluation-adk-testsuite.png)

---

## 1. Concepts & terms (glossary)

- **Plan / TestPlan** — the Stage-A artifact for one `context_id`: structured `methodology`, `scope`,
  `out_of_scope`, `metrics` (what "passed" means), `confidence`, `source_refs`, `status` (`draft`/`confirmed`),
  plus a human-facing **brief** (`define/plan.py::assemble_plan` / `heuristic_brief` / `claude_brief`).
- **PlanDecision** — one distilled, provenance-carrying answer to a define question. A **human** answer →
  a `decision` (high confidence); an **agent self-answer** → a vetoable `assumption` (low confidence)
  (`define/decision.py`). Decisions assemble into the TestPlan.
- **Suite** — the Stage-B artifacts: `TestData`, `TestScenario`s, `TestStep`s, and the exported Gherkin
  `.feature` (`implement/generate.py`, `render/gherkin.py`).
- **Coverage matrix** — per in-scope behaviour, the scenario **kinds** the agent generates:
  `_FULL_COVERAGE = (HAPPY, NEGATIVE, BOUNDARY, ERROR)` (`implement/scenarios.py`), downgraded to happy-only
  when a metric string literally says "happy only". The equivalence-partitioning + boundary-value-analysis
  surface.
- **Behaviour / AC** — one acceptance-criterion proxy in the pack: a **grounded note**
  (`plan_pack.pack.grounded`). Scenarios are generated one-per-behaviour × the matrix, each carrying
  `source_refs=[note.id]` back to the behaviour it covers.
- **Traceability** — the bidirectional link AC↔scenario. Forward: does every in-scope AC have a scenario?
  Backward: does every scenario cite a real pack node? Encoded as graph edges `scenario→insight`
  (`implement/generate.py::_add_provenance`).
- **Oracle** — what a scenario *asserts*. A **strong** oracle verifies the end-state (the metrics round's
  "End-state verified"); a **weak** oracle asserts only acceptance / a status code ("Accepted"). Oracle
  strength is the difference between a test that catches a regression and one that always passes.
- **Golden set / plan-evalset** — a human-curated set of `(pack, reference_plan, reference_suite)` triples;
  the ground truth every metric scores against. The star anchor is a **human-authored, executed** plan.
- **Mutation score** — fraction of injected faults (mutants) in the system-under-test that the suite would
  **kill** (fail on). The gold-standard measure of fault-detection adequacy; needs runnable tests → gated on
  the execution stage.
- **Deterministic vs judged** — deterministic metrics are computed by code over ids/sets/structure (set
  overlap, partition presence, placeholder regex) → cheap, stable, PR-gate-able. Judged metrics prompt an LLM
  (faithfulness, oracle-strength rubric) → non-deterministic, sampled, nightly.

---

## 2. What "good" means for a test-plan agent

The TPD's "answer" is not a chat reply and not a retrieval pack — it is a **plan + a suite**. A good one has
five properties, each mapping to a metric family. Every "failure we've seen" below is a real, recorded TPD
incident.

| Property | Plain meaning | Failure we've actually seen | Metric family |
|---|---|---|---|
| **On-scope** | the plan tests *this* feature and its load-bearing integrations — not excluded nodes | define brief auto-scoped LUZ-159312 to the **excluded** subtasks + said "nothing out of scope" | **Scope Precision/Recall**, Faithfulness, `hallucinations_v1` |
| **Complete** | every in-scope behaviour has a scenario, in every needed partition | silent heuristic fallback shipped **3 of 6+ behaviours** | **AC-Coverage Recall**, **Coverage-Matrix Completeness** |
| **Discriminating** | a scenario would actually *fail* on a regression — real oracle, not `assert 200` | execution-depth gap: placeholder oracles vs the human plan's real end-states | **Oracle Strength**, **Mutation Score** (later) |
| **Traceable** | every scenario cites the AC it covers; nothing invented | scenario `source_refs` must point at real pack nodes | **Traceability**, provenance-edge validity |
| **Well-driven & honest** | right define→implement path; assumptions flagged, gaps declared | empty interrogation → false "high confidence" | ADK **trajectory**, **Interrogation Yield**, Goal Accuracy |

The rest of the report turns this table into concrete metrics, thresholds, and a harness.

---

## 3. The TPD as an evaluation target

The TPD is **two engines** in series, and they demand different metrics:

- a **judgement engine** (Stage A / define) — a 3-round interrogation (`methodology → scope → metrics`) that
  distills human calls into a structured plan. Its output is *decisions* and a *brief*. Score it for
  groundedness, scope correctness, and honest confidence.
- a **generation engine** (Stage B / implement) — one-shot expansion of the confirmed plan into a suite. Its
  output is *scenarios/steps/data*. Score it for coverage, traceability, oracle strength, and (eventually)
  fault detection.

Pin down which stages are **deterministic** (trajectory / set metrics fit; expect exact scores) vs
**stochastic** (LLM-judged; expect variance and sample). This matters because ADK's `tool_trajectory_avg_score`
defaults to a hard **1.0** — only legitimate on the deterministic skeleton.

| Stage | Code | Deterministic? | Engine | Notes |
|---|---|---|---|---|
| Round order `methodology→scope→metrics` | `models/plan.py::ROUNDS` | ✅ | Judgement | fixed dependency order |
| Question generation per round | `define/questions.py` (heuristic **or** Claude-on-Vertex) | ⚠️ LLM-or-heuristic | Judgement | falls back to heuristic on empty — *which path?* |
| Self-answer of the coverage bar | `round/metrics.py` (`status="self-answered"`) | ✅ | Judgement | a vetoable assumption, always low-confidence |
| Decision distillation | `define/decision.py` | ✅ | Judgement | human→decision(high); self→assumption(low) |
| Plan assembly | `define/plan.py::assemble_plan` | ✅ | Judgement | scope/method/metrics from decision rounds |
| Confidence | `define/plan.py::confidence` | ✅ | Judgement | opens→low; assumption→medium; else high |
| Prose brief | `heuristic_brief` **or** `claude_brief` (M6) | ⚠️ LLM-or-heuristic | Judgement | the headline "answer" of Stage A |
| Test-data generation | `implement/testdata.py` (heuristic default; LLM on `detail`) | ⚠️ | Generation | placeholders `<generated>`/`<expected>` in heuristic |
| Scenario generation | `implement/scenarios.py` (`_FULL_COVERAGE`; LLM on config) | ⚠️ LLM-or-heuristic | Generation | matrix per behaviour; **silent fallback risk** |
| Step generation | `implement/steps.py` (keyworded heuristic; LLM on `detail`) | ⚠️ | Generation | Given/When/Then; `_STEP_BATCH=8` |
| Gherkin export | `render/gherkin.py` | ✅ | Generation | tags `@kind @methodology` |
| Provenance edges | `implement/generate.py::_add_provenance` | ✅ | Generation | scenario→insight edges (traceability) |

**The single most important consequence:** the Stage-A brief and the Stage-B scenarios each have a *heuristic*
path and an *LLM* path, and the code **silently** falls back heuristic→ when the LLM returns nothing or
truncates. So **every content metric must record which path produced the artifact** — a tailored title means
the LLM ran; a `_KIND_SUFFIX` string ("— happy path") means the heuristic ran. A truncated-JSON fallback that
drops half the behaviours is otherwise invisible. This is the TPD analog of the KGA's "two retrievers" twist.

---

## 4. Lens 1 — Google ADK Evaluation (controller + groundedness)

### 4.1 The data model (reused)

ADK structures eval as **EvalSet → EvalCase → Invocation**. For the TPD, one EvalCase records, for one pack:
the input (`define <ctx>` … the answer sequence … `approve_plan` … `implement_plan`), the **expected
tool-use trajectory**, and the **reference plan/brief**. Author two ways: `adk eval` on a saved
`.evalset.json`, or `AgentEvaluator.evaluate()` inside `pytest`. Thresholds live in a separate **EvalConfig**.
We reuse the KGA harness's schema verbatim (§8) so both agents share one eval codebase.

### 4.2 The metrics that apply to the TPD

| ADK config key | Measures | TPD mapping | Value |
|---|---|---|---|
| `tool_trajectory_avg_score` | exact match of the tool-call sequence (EXACT / IN_ORDER / ANY_ORDER) | outer `define_plan → approve_plan → implement_plan`; inner `methodology → scope → metrics` round order | **HIGH** — deterministic, regression-prone |
| `hallucinations_v1` | splits the response into sentences, checks each is **grounded** in the provided context | is every claim in the **brief** traceable to a pack note? guards the "brief ignores the pack" bug | **CRITICAL** |
| `final_response_match_v2` | LLM-judged **semantic** match of the final response to a reference | brief vs a **reference brief** (paraphrastic — prefer over ROUGE) | HIGH for the brief |
| `response_match_score` | ROUGE-1 overlap vs reference | only the deterministic summary line (`summarize_implement`: "N scenarios (H happy / N negative)") | LIMITED |
| `rubric_based_final_response_quality_v1` | LLM-judged quality against **custom rubrics** you write | the TPD-specific rubrics in §6 ("scope excludes the excluded nodes", "oracle asserts an end-state", "no placeholder leaked") | **HIGH, later** |
| `safety_v1` | harmlessness | the TPD is read-only planning; low risk | LOW (cheap floor) |

`EvalConfig` shape (identical schema to the KGA report — one config, two agents' criteria):

```json
{
  "criteria": {
    "tool_trajectory_avg_score": 1.0,
    "final_response_match_v2": {
      "threshold": 0.8,
      "judge_model_options": { "judge_model": "gemini-2.5-flash", "num_samples": 5 }
    },
    "hallucinations_v1": { "threshold": 0.8, "judge_model_options": { "judge_model": "gemini-2.5-flash" } }
  }
}
```

### 4.3 RAGAS generation metrics — the same-intent cross-check

The TPD is not a retriever, so RAGAS's *retrieval* metrics (Context Precision/Recall) do **not** apply to it
the way they do to the KGA. But RAGAS's **generation** metrics score exactly the brief-groundedness surface,
and are worth running as a second opinion next to ADK `hallucinations_v1`:

- **Faithfulness** — fraction of claims in the brief supported by the pack (same intent as
  `hallucinations_v1`). *Catches the "brief ignores the pack" bug directly.*
- **Response Relevancy** — does the brief address *this pack's* subject, not a neighbour's?

Each RAGAS sample is `{user_input = pack subject, response = brief, retrieved_contexts = pack note synopses,
reference = reference brief}`. Note the retrieved_contexts here are the *pack the TPD was handed*, not
something the TPD fetched — we are scoring whether the generator was faithful to its input, which is the whole
game for a downstream agent.

---

## 5. Lens 2 — Test-suite adequacy & quality (the heart of this report)

This is the lens the KGA did not need. A test-plan agent must be judged the way any test suite is judged, by
the established measures of software-testing science. Five families, from cheapest/most-deterministic to most
expensive/most-truthful.

### 5.1 Coverage adequacy — did the suite cover the behaviours and their partitions?

| Metric | Definition | Needs golden | TPD mapping |
|---|---|---|---|
| **AC-Coverage Recall** | of the in-scope behaviours (ACs), how many have ≥1 scenario tracing to them | golden `behaviours` list | of the pack's grounded notes, how many appear in some scenario's `source_refs`. **Catches the silent-fallback drop** (3 of 6 behaviours → recall 0.5). |
| **Coverage-Matrix Completeness** | of the required partitions per behaviour, how many are present | golden `expected_partitions` per behaviour | for each behaviour, are `happy/negative/boundary/error` scenarios present (unless the plan is legitimately happy-only)? Scores `_FULL_COVERAGE` vs what shipped. |
| **Scenario Precision** | fraction of scenarios that map to an in-scope behaviour (no scenarios for excluded/invented nodes) | golden `in_scope` + `must_not_scope` | any scenario tracing to a `must_not_scope` node fails — the **hard-negative** gate. |
| **Traceability Completeness** | every scenario has a resolvable `source_refs`; every AC → scenario; bidirectional | golden mapping | validates `_add_provenance` edges resolve to real pack nodes (IEEE 29119 traceability). |

Coverage-Matrix Completeness is the equivalence-partitioning + boundary-value-analysis measure made concrete:
the agent's own `_FULL_COVERAGE = (HAPPY, NEGATIVE, BOUNDARY, ERROR)` **is** the partition model, so we score
against it directly. It also catches the brittle downgrade: `_coverage_kinds` drops to happy-only on a raw
substring match of `"happy only"` in the metrics text — the metric must check *actual partition presence*, not
trust the metric string.

### 5.2 Fault-detection adequacy — would the tests catch a bug?

This is the deepest question and the one that separates a *plausible* suite from an *effective* one.

- **Mutation Score (the gold standard, later).** Inject small faults (mutants) into the system under test and
  measure the fraction the suite **kills**. Established since Jia & Harman's survey; on the JVM (the luz stack
  is Java) the tool is **PIT/pitest**. This requires the scenarios to *run* — which needs the execution stage
  from [`RESEARCH-test-executor-agent.md`](./RESEARCH-test-executor-agent.md) Pillar 2. **Not
  available today.** When it is, mutation score becomes the TPS's heaviest term.
- **Oracle Strength (the deterministic proxy, now).** A test that asserts only `2xx` kills almost no mutant;
  a test that asserts the real end-state kills many. Score each scenario/step for oracle strength:
  - **weak** — asserts a status code / "accepted" only (`_HAPPY_STEPS` "the response status is 2xx");
  - **medium** — asserts a named end-state placeholder (`PASS_METRIC` resolved to the plan's pass-criterion);
  - **strong** — asserts a concrete, resolvable end-state (a real field/state from the pack, e.g.
    `CREDIT_CARD_CHARGED_PENDING`).

  This is measurable *without running anything* and is a strong predictor of mutation score. It directly
  encodes the **execution-depth gap**: the metrics round's "Accepted vs End-state verified" choice becomes a
  gradeable oracle-strength target.
- **Fault-class coverage (proxy, now).** For each behaviour, the golden set lists its **known fault classes**
  (e.g. for dunning: "retry fires on the wrong `failCount` day", "QR fallback wrongly removed for a COMPANY
  tenant"). Score whether the suite has a scenario aimed at each class. A checklist stand-in for mutation
  until the real thing runs.

### 5.3 Executability / validity — are the artifacts real or placeholders?

The LLM-test-generation literature scores generated tests for **validity** (do they compile/parse/run) before
anything else *(the specific numbers vary by study — treat as directional, unverified)*. The TPD analog is a
**placeholder-leak** check: the heuristic test-data path emits `{"id": "<generated>", "status": "<expected>"}`
and `<test-tenant>`; a step template leaves `PASS_METRIC` to be resolved. A "detail" (LLM) run that still ships
these tokens has silently fallen back to the heuristic. Deterministic regex over the artifacts:

- no `<generated>` / `<expected>` / `<test-tenant>` / `PASS_METRIC` survives a `detail=True` run;
- every `data_refs` id resolves to a generated `TestData` id;
- every step's `expected` is non-empty.

### 5.4 Redundancy & minimality — is the suite lean?

- **Scenario redundancy** — near-duplicate scenarios (same behaviour, same partition, different words) inflate
  the count without adding coverage. Deterministic first pass: `(source_ref, kind)` pairs should be unique
  (the heuristic guarantees this; the LLM path can duplicate). LLM upgrade: semantic near-duplicate detection.
- **Minimality** — INVEST-style; a scenario should verify **one** behaviour. Feeds the BDD-quality metric.

### 5.5 BDD / Gherkin quality — is the `.feature` well-formed?

The exported `.feature` (`render/gherkin.py`) is what the downstream execution stage and the
`implement-bdd-steps` skill consume, so its quality matters. Established Gherkin "smells" *(Cucumber docs +
practitioner literature; some points unverified)*:

- **Declarative, not imperative** — steps state intent ("a valid request is sent"), not UI mechanics.
- **One behaviour per Scenario** — no conjunctive "and also" scenarios.
- **No conjunctive steps** — a single `When` per action (the `_KIND_STEPS` templates already respect this).
- **Tag hygiene** — every Scenario tagged `@<kind> @<methodology>` (the exporter guarantees this — assert it).
- **Given/When/Then well-formed** — a Given (arrange), a When (act), a Then (assert); the heuristic templates
  satisfy this by construction, the LLM path must be linted.

---

## 6. The mapping — TPD stage × metric matrix (core deliverable)

The table to implement against. "Det." = deterministic/cheap (PR gate). "Judge" = LLM-judged (nightly).
"Exec" = needs the execution stage (gated).

| TPD stage / artifact | Primary metric(s) | Lens | Kind | Ground truth needed |
|---|---|---|---|---|
| Outer `define→approve→implement` | `tool_trajectory_avg_score` (IN_ORDER) | ADK | Det. | expected tool list |
| Inner rounds `methodology→scope→metrics` | `tool_trajectory_avg_score` | ADK | Det. | expected round order |
| Interrogation yield | **questions raised / pack-richness** + Agent Goal Accuracy | ADK/testing | Det.+Judge | expected ≥1 open question on a rich pack |
| Plan **scope** (`scope` / `out_of_scope`) | **Scope Precision / Recall** (set-overlap) + `must_not_scope` hard-neg | testing | Det. | golden in-scope + excluded ids |
| Plan **methodology** | exact match | testing | Det. | golden methodology |
| Plan **metrics / pass-criteria** | **Oracle Strength** of the criterion (end-state vs accepted) | testing | Det.+Judge | golden pass-criteria |
| Plan **brief** groundedness | **Faithfulness** / `hallucinations_v1` | ADK/RAGAS | Judge | — |
| Plan **brief** correctness | `final_response_match_v2` + Semantic Similarity | ADK | Judge+Det. | reference brief |
| Plan **confidence** honesty | rubric: confidence matches open-gap count | testing | Det. | — |
| Decisions provenance | every decision has `source_refs`; assumptions flagged | testing | Det. | — |
| Test-data | placeholder-leak (Det.) + role/entity grounding (Judge) | testing | Det.+Judge | — |
| **Scenarios: AC coverage** | **AC-Coverage Recall** (source_ref set-overlap) | testing | Det. | golden behaviours |
| **Scenarios: partitions** | **Coverage-Matrix Completeness** | testing | Det. | golden partitions per behaviour |
| **Scenarios: precision** | Scenario Precision + `must_not_scope` gate | testing | Det. | golden in/excluded ids |
| Scenarios: redundancy | `(source_ref, kind)` uniqueness (Det.) + semantic dedup (Judge) | testing | Det.+Judge | — |
| Steps: oracle | **Oracle Strength** distribution | testing | Det.+Judge | golden pass-criteria |
| Steps: concreteness | **execution-depth**: real endpoint/state vs placeholder | testing | Judge | reference plan |
| Gherkin `.feature` | BDD/Gherkin lint (tags, one-behaviour, declarative) | testing | Det.+Judge | — |
| **Whole suite: fault detection** | **Mutation Score** (real) / fault-class coverage (proxy) | testing | Exec / Det. | golden fault classes |
| Whole run | Agent Goal Accuracy (confirmed, on-scope, non-empty suite) | ADK | Judge | binary label |

**Composite "Test-Plan Score" (TPS).** A single weighted mean for dashboards, weighting the **silent-failure**
surfaces highest because our real incidents were a bled brief and shallow oracles, not too-few scenarios:

```
TPS = 0.30·FaultDetection            # mutation score (real) OR oracle-strength+fault-class-coverage (proxy)
    + 0.25·BriefGroundedness         # faithfulness / hallucinations_v1 + scope precision/recall
    + 0.20·CoverageCompleteness      # AC-coverage recall × coverage-matrix completeness
    + 0.15·OracleStrength            # (folded out of FaultDetection while it is a proxy — see note)
    + 0.10·TrajectoryScore           # define→approve→implement + round order
```

Fault-detection and groundedness weigh highest for the same reason the KGA weighted faithfulness+precision
highest: a **thin** suite is a *visible* failure a human catches; a **full-looking-but-shallow** suite (all
oracles are `assert 200`) or a **confidently-bled** brief (scopes the excluded nodes) *looks* done and fools
you. The silent failure modes get the heavier weights. **Always emit the components** next to the number — a
0.04 TPS drop could be all oracle-strength or all coverage, and you must know which surface regressed to act.
While mutation is a proxy, fold OracleStrength into the FaultDetection term (they measure the same thing at
different fidelities) and re-split once real mutation lands.

---

## 7. The golden dataset (plan-evalset) design

The harness is only as good as the golden set. Curate **8–15 packs** spanning the shapes that break the TPD.
Crucially, the TPD golden set can be **anchored to a real, executed, human-authored plan** — a ground truth
the KGA never had.

| Pack shape | Example | Why it's in the set |
|---|---|---|
| Rich, code-grounded pack | LUZ-159312 (luz_finance codegraph) | happy path; high AC-recall + partition completeness expected |
| **Excluded-nodes pack** | LUZ-159312 with siblings/file-import explicitly excluded | the **define-brief-scoping bug**: tests Scope Precision + `must_not_scope` |
| **Thin pack** (title only) | any title-only ticket | tests Interrogation Yield + the empty-interrogation false-positive |
| Recorded-only integrations | a pack with un-followed integration links | tests the scope round's `recorded_only_types()` questions |
| Happy-only vs full-matrix | one metrics="happy only", one default | tests Coverage-Matrix Completeness in both modes |
| **Human-executed reference** | **LUZ-156281 "Invoice Run Dunning Tests"** (~83 cases, real endpoints/states) | the star anchor: real AC-recall / oracle-strength / execution-depth benchmark |

Per pack, author a small JSON (ADK EvalCase-compatible) with the **minimum viable ground truth**:

```json
{
  "context_id": "run-159312",
  "expected_trajectory": ["define_plan", "approve_plan", "implement_plan"],
  "expected_rounds": ["methodology", "scope", "metrics"],
  "in_scope_ids":       ["jira:LUZ-159312", "codegraph:luz_finance/InvoiceRunController"],
  "must_not_scope_ids": ["jira:LUZ-159313", "jira:LUZ-158446", "jira:LUZ-158824"],
  "behaviours": [
    {"id": "jira:LUZ-159312#retry",  "expected_partitions": ["happy","negative","boundary","error"],
     "fault_classes": ["retry fires on wrong failCount day", "second-consecutive-fail not detected"]},
    {"id": "jira:LUZ-159312#qr",     "expected_partitions": ["happy","negative"],
     "fault_classes": ["QR fallback removed for COMPANY tenant (should be individual-only)"]}
  ],
  "pass_criteria": ["end-state: tracking row reaches CREDIT_CARD_CHARGED_PENDING"],
  "reference_plan_ref": "docs/luz-159312-test-plan.html",
  "reference_executed_plan": "artifact:fa6604ec (LUZ-156281 dunning, ~83 cases)"
}
```

- `in_scope_ids` / `must_not_scope_ids` → Scope Precision/Recall by set overlap; **any `must_not_scope`
  appearance is a hard fail** (this encodes the define-brief-scoping bug guard directly).
- `behaviours[].expected_partitions` → Coverage-Matrix Completeness.
- `behaviours[].fault_classes` → the fault-class-coverage proxy for mutation.
- `pass_criteria` → Oracle Strength target for the steps.
- `reference_executed_plan` → the depth/recall benchmark; the single most valuable anchor.

Store the golden set in `test-agent/src/test_evaluation/golden_plans/*.json` (a sibling of the shipped
`golden/` KGA seeds, loaded the same way via `golden.py`); keep it in git (it is the spec of a good plan).
Reuse the shipped agent's conventions — a typed `PlanEvalCase` in `models.py` (mirroring `EvalCase`), one JSON
per pack — so **one eval agent serves both** the KGA and the TPD. The PlanPack **fixtures** the harness replays
live test-side under `tests/eval/`.

---

## 8. Harness design

**Offline, deterministic-first, LLM-judged-nightly, mutation-when-executable.** Mirror the KGA harness (§8 of
the sibling) and the codebase's discipline: blocking LLM calls are `asyncio.to_thread`-offloaded; expensive
tiers default OFF; the harness runs **out of band** (never in `execute()` — a serial-Vertex implement already
killed a Cloud Run instance on `ERROR_TIMEOUT`).

Retargeted onto the **shipped third agent** (the KGA half already exists there — this adds the TPD metrics +
an `evaluate_plan` engine into the *same* package, and the TPD harness test-side):

```
src/test_evaluation/            # the deployed eval agent (KGA scoring already lives here)
  models.py                     # + PlanEvalCase, PlanScore, ScopeScore, CoverageScore, OracleScore, TPSComponents/Result
  metrics/
    trajectory.py               # ALREADY SHIPPED — reused verbatim (outer flow + inner round order)
    pqs.py  history.py  rubrics.py   # ALREADY SHIPPED — tps.py mirrors pqs.py; history/rubrics reused
    scope_overlap.py            # NEW — Scope P/R + must_not_scope hard-negative (mirrors node_overlap.py)
    coverage.py                 # NEW — AC-coverage recall + coverage-matrix completeness + traceability
    oracle.py                   # NEW — oracle-strength classifier (weak/medium/strong)
    placeholders.py             # NEW — placeholder-leak + validity
    gherkin_lint.py             # NEW — BDD smells
    groundedness.py             # NEW — RAGAS faithfulness / ADK hallucinations_v1 over the brief (LLM)
    mutation.py                 # NEW — fault-class coverage now; real PIT hook later (Exec)
    tps.py                      # NEW — the weighted composite (copy pqs.py's typed PQSResult shape)
  golden_plans/*.json           # §7 curated packs, one PlanEvalCase each (sibling of golden/)
  engine.py                     # + evaluate_plan(bank, ctx, case) -> PlanReport (peer to evaluate_pack)
  executor/  bridge/            # + an evaluate_plan skill/tool on the existing A2A executor + MCP bridge

tests/eval/                     # out-of-band harness + tests (imports test_plan_definition → test-side)
  fixtures/packs/<CTX>.json     # a recorded, approved PlanPack (grounded notes + understanding) — no live GCS
  harness_tpd.py                # run_define_offline / run_implement_offline + PlanTrace (next to harness.py)
  test_eval_tpd_deterministic.py  # T0 + T1 (PR gate)
  test_eval_tpd_judged.py         # T2 + T3 (nightly)
  test_eval_tpd_mutation.py       # T4 (gated on the execution stage)
```

**Three tiers of run:**

1. **PR gate (seconds, no LLM, no network).** Drive `run_define_offline` + `run_implement_offline`
   in-process against a **recorded PlanPack fixture** and a **temp bank**. Compute trajectory, scope
   overlap + `must_not_scope`, AC-coverage recall, coverage-matrix completeness, traceability,
   placeholder-leak, Gherkin lint. Fail the PR on any golden regression. Fully deterministic → safe as a
   required check.
2. **Nightly / `eval:` label (minutes, LLM).** RAGAS Faithfulness / Response Relevancy + ADK
   `hallucinations_v1` on the brief; LLM oracle-strength and execution-depth rubric on the steps; semantic
   redundancy. Post **TPS + component deltas** vs the last main-branch baseline.
3. **Execution tier (gated on Pillar 2).** Once the scenarios become runnable, wire real **PIT mutation
   score** against the SUT. Until then `test_eval_mutation.py` computes only the fault-class-coverage proxy.

**Reuse, don't rebuild.** The TPD already exposes everything read-only: `get_plan` for the brief,
`get_scenarios` for the suite, the persisted decisions/questions/answers, and the `TestPlanRun` log
(`questions_raised/answered`, `scenarios_written`, `confidence`, `gaps`). The harness reads the same artifacts
a human reviews — and shares the temp-bank + recorded-fixture discipline with the KGA harness (never the prod
`GCS_BUCKET`, which a redeploy has silently wiped before).

**Determinism & flakiness.** LLM-judged metrics vary run-to-run — sample `num_samples≥3`, compare **means**,
gate on a **delta band** ("oracle-strength dropped >0.05 vs baseline"), never an absolute single-sample
pass/fail. Deterministic metrics gate absolutely.

---

## 9. What the metrics would have caught (retro-fit to real incidents)

Each recorded TPD incident maps to a metric that would have flagged it **before** a human noticed — the
strongest argument for building this.

| Incident (from project history) | Metric that flags it | How |
|---|---|---|
| **Define brief ignores answers AND the pack** (auto-scoped LUZ-159312 to excluded subtasks + "nothing out of scope") | **Scope Precision ↓**, `must_not_scope` **leak**, Faithfulness ↓, `hallucinations_v1` ↓ | the golden pack lists the excluded siblings/file-import in `must_not_scope_ids`; the scope including them is an instant hard fail; the brief citing them fails faithfulness vs the approved understanding. |
| **Silent heuristic fallback** (LLM JSON truncated → 3 of 6+ behaviours shipped) | **AC-Coverage Recall ↓**, which-path provenance | 6 golden behaviours, 3 in `source_refs` → recall 0.5; the shipped titles are `_KIND_SUFFIX` strings → provenance flag says "heuristic", contradicting a `detail` run. |
| **Execution-depth gap** (placeholder oracles vs the human plan's real endpoints/states; wrong billing facts) | **Oracle Strength ↓**, execution-depth rubric ↓, (later) **Mutation Score ↓** | steps asserting `2xx`/`PASS_METRIC` score "weak/medium"; the reference executed plan asserts `CREDIT_CARD_CHARGED_PENDING` → "strong"; the gap is the score. Fault-class coverage shows the "QR-fallback COMPANY-vs-individual" class untested. |
| **Empty interrogation** ("high confidence", 0 questions on a rich pack) | **Interrogation Yield ↓**, Agent Goal Accuracy = 0 | a rich golden pack expects ≥1 open question; zero on a rich pack is a false-positive smell → goal not achieved; the resulting "confident" plan is generic → low relevancy. |
| **Happy-only silent narrowing** (metric string flips the matrix off) | **Coverage-Matrix Completeness ↓** | the metric checks *actual* partition presence per behaviour, not the `"happy only"` substring — a plan that should have negatives but shipped none fails. |
| **Placeholder leak on a `detail` run** (`<generated>`/`PASS_METRIC` survives) | **placeholder-leak = fail** | deterministic regex; a `detail=True` run that leaks a placeholder has silently fallen back to the heuristic. |

---

## 10. Phased roadmap

Cheap, deterministic value first; expensive LLM judging next; real fault detection last (it depends on a stage
that isn't built). Same "default-OFF, earn-the-cost" pattern the agents already follow, and the same T-naming
shape as the KGA report's E0–E4 so the two roadmaps read as one program.

- **T0 — Golden set + trajectory (days, no LLM).** Curate 8–15 packs (§7), **including the LUZ-156281 executed
  plan** as the reference anchor. Record PlanPack fixtures. Ship `tool_trajectory_avg_score` +
  `define→approve→implement` + round-order assertions as a **required PR check**. Immediate control-flow
  regression safety.
- **T1 — Deterministic plan + coverage scores (days, no LLM).** Scope Precision/Recall + the `must_not_scope`
  hard-negative gate (**catches the define-brief-scoping bug**); AC-Coverage Recall + Coverage-Matrix
  Completeness (**catches the silent fallback + happy-only narrowing**); Traceability; placeholder-leak +
  which-path provenance. Still deterministic → still a PR gate. **T0+T1 alone would have caught the two
  worst real incidents.**
- **T2 — Groundedness + oracle judging (week, LLM, nightly).** RAGAS Faithfulness + Response Relevancy and
  ADK `hallucinations_v1` over the brief; LLM oracle-strength classifier over the steps. Report TPS +
  component deltas on `eval:`-labelled PRs. Sample means, gate on a band.
- **T3 — Scenario quality + execution-depth (week, LLM, nightly).** Semantic redundancy; Gherkin smells;
  the **execution-depth rubric** (real endpoint/state vs placeholder) benchmarked against the reference
  executed plan. Now the concreteness gap the human plan exposed becomes a *number*.
- **T4 — Real mutation + TPS dashboard (gated on Pillar 2, then ongoing).** When the execution stage
  ([`RESEARCH-test-executor-agent.md`](./RESEARCH-test-executor-agent.md)) can run the scenarios, wire
  **PIT mutation score** and swap it in for the proxy in the TPS. Trend TPS over time; alert on a main-branch
  regression naming the offending component.

| Phase | Depends on | LLM? | Gate | Rough effort |
|---|---|---|---|---|
| T0 | — | no | PR-required | 2–3 days |
| T1 | T0 scaffolding | no | PR-required | 2–3 days |
| T2 | T0 + define/implement drivers | yes | nightly | ~1 week |
| T3 | T2 | yes | nightly | ~1 week |
| T4 | **execution stage (Pillar 2)** + T2/T3 | yes | dashboard | gated + ongoing |

Ship T0+T1 first — deterministic, cheap, and alone they catch the define-brief-scoping bug **and** the silent
fallback. Treat T2–T3 as the quality layer that earns its token cost nightly. T4 is explicitly **blocked** on
the missing execution stage — which is the clean seam between this report and its sibling: the KGA report
scores retrieval, this one scores planning, and both hand off to the execution pillar the agentic-qa report
scopes.

---

## 11. Constraints & gotchas (from this system's own history)

- **Never run eval inside the agent request path.** Serial blocking Vertex calls in `implement` already
  starved Cloud Run's `/livez` and killed an instance (`ERROR_TIMEOUT`); the harness runs **out of band**
  (pytest/CI), never in `execute()`. Mirror the codebase's `asyncio.to_thread` offload if any judged metric
  runs in-process.
- **A truncated-JSON LLM fallback is silent — always record which path ran.** Quadrupling the coverage matrix
  overran `max_tokens` (2000→6000 fixed it) and the generator *silently* fell back to the capped heuristic,
  shipping half the behaviours. Every content metric must carry a provenance flag (LLM vs heuristic); a
  `detail=True` run that produced `_KIND_SUFFIX` strings is a failure even if the counts look fine.
- **The define brief is the known-broken surface — lock it hardest.** The brief writer ignores both the
  answers and the approved pack (it auto-scopes to `grounded[0].id` and can pick the *excluded* nodes). Treat
  Scope Precision/Recall + the `must_not_scope` hard-negative as a **required** gate, not a nightly nicety.
- **`_coverage_kinds` is a brittle substring match.** It downgrades to happy-only on `"happy only"` in the
  metrics text — the Coverage-Matrix metric must check *actual partition presence*, never the metric string.
- **GCS bank state can vanish on redeploy.** A redeploy silently wiped a `context_id`'s whole bank once. The
  harness uses a **temp/isolated bank + recorded PlanPack fixtures** — never the prod `GCS_BUCKET`.
- **Mutation needs a runnable SUT.** The truest metric is gated on the not-yet-built execution stage; until
  then, oracle-strength + fault-class coverage are the honest proxy, and the report says so.
- **Codegraph grounding gives structure, not execution depth.** A code-grounded plan gets controller names and
  flow but not real endpoints/states/log-markers — the execution-depth rubric (T3) must benchmark against a
  human-executed plan, or it will reward a plausible-but-shallow suite.
- **LLM-judged metrics are non-deterministic and cost tokens.** Default them OFF in the PR gate; sample and
  compare means nightly. Deterministic set-overlap + coverage + placeholder checks carry the required weight.
- **The working tree, not the commit, is what runs.** `gcloud builds submit` and pytest both use the working
  tree — gate on a clean tree so an eval pass can't mask an uncommitted edit.
- **Self-learning (L3/L4) is a moving target under eval.** The `_capture_define` / `_recall_into` hooks mean a
  later run can differ from an earlier one on the *same* pack. Run the golden set with recall **disabled** for
  the deterministic gate (reproducibility), and evaluate the learning effect as its own before/after metric.

---

## 12. Sources

Primary (preferred):
- **ISTQB Certified Tester Foundation Level syllabus** — test-design techniques (equivalence partitioning,
  boundary value analysis, decision tables), requirements coverage, traceability.
- **ISO/IEC/IEEE 29119** (software testing — test techniques, coverage items, traceability) and **IEEE 829**
  (test documentation).
- **Y. Jia & M. Harman, "An Analysis and Survey of the Development of Mutation Testing,"** IEEE TSE 37(5),
  2011 — mutation testing as the fault-detection-adequacy gold standard.
- **PIT / pitest** (`pitest.org`) — mutation testing for the JVM (the luz stack is Java).
- **Google ADK — evaluation docs** (`google.github.io/adk-docs/evaluate/`) and
  **`adk-python` `eval_metrics.py` (`PrebuiltMetrics`)** — trajectory / `hallucinations_v1` /
  `final_response_match_v2` / rubric metrics (cross-checked in the sibling KGA report).
- **RAGAS — generation metrics** (`docs.ragas.io`) — Faithfulness, Response Relevancy.
- **Cucumber / Gherkin reference** (`cucumber.io/docs/gherkin`) — declarative-vs-imperative, anti-patterns.

Secondary / corroborating (treated as *unverified* where they exceed the primary standards):
- LLM-test-generation empirical studies (validity / coverage / mutation of generated tests) — directional
  evidence that validity gates precede coverage which precedes fault detection; specific percentages vary by
  study and are not relied on here.
- BDD "scenario smell" practitioner literature — the Gherkin quality checklist in §5.5.

*Cross-check status: ADK + RAGAS metric names are carried over from the sibling report's verified source list.
The testing-science measures (coverage adequacy, mutation, traceability) are standard and well-attested in
ISTQB / IEEE 29119 / Jia-Harman. Claims specific to LLM-test-gen numbers and BDD-smell taxonomies are marked
unverified and used only as directional support, not as thresholds.*

---

## Appendix A — Implementation plan (phase by phase) — **re-pointed at the shipped eval agent**

> **Status: BUILT (2026-09-05) — deterministic T0/T1 + composite; LLM tiers gated.** The TPD-scoring metrics
> now live in the eval **agent** the sibling KGA report produced — [`src/test_evaluation/`](../src/test_evaluation/)
> — as designed here: the plan is **extended into that agent**, not a parallel `tests/eval/metrics/` tree.
> The phase headings below read as the as-built record. Build-out of
> the §10 roadmap: the metrics + an `evaluate_plan` engine land in **`src/test_evaluation/`** (peer to the
> `evaluate_pack` engine); only the TPD **harness** (`run_define_offline`/`run_implement_offline`) lands under
> **`tests/eval/`** (it imports `test_plan_definition`, so it stays test-side). Reuse the shipped conventions:
> typed dataclasses in `models.py` (**no bare dicts** — the code snippets below are updated to match),
> `metrics/trajectory.py` verbatim, and `metrics/pqs.py` / `history.py` / `rubrics.py` as the templates for
> `tps.py` / history / rubrics. Deterministic phases (T0–T1) are required PR checks; judged phases (T2–T3) run
> nightly / on an `eval:` label; the mutation phase (T4) is gated on the execution stage. Each phase is
> independently shippable and leaves the suite green.

### Shared scaffolding (built once, in T0)

The harness drives both TPD executors **in-process** — no HTTP, no Cloud Run, no live GCS — mirroring the
shipped KGA harness (`tests/eval/harness.py`: Starlette `TestClient` + JSON-RPC over the real A2A stack, a
`FakeBucket`-backed `MemoryBank`, and refine driven through `common.interrogate.loop.refine`).

- **`recorded_pack`** — a persisted, approved `PlanPack` fixture per golden context (grounded notes + the
  confirmed understanding), written once to `fixtures/packs/<CTX>.json` from a real approved run and committed.
  No network in CI.
- **`temp_bank`** — a `MemoryBank` on `tmp_path` (or `fsspec` `memory://`) so a harness run never touches the
  prod `GCS_BUCKET`. Reuses `common.executor.build_bank` with an overridden bucket/root; loads the
  `recorded_pack` into it.
- **`run_define_offline(ctx, answers)`** — drive `PlanSession` to completion with a scripted answerer
  (the golden answers), returning a `PlanTrace` (`plan`, `brief`, `decisions`, `rounds`, `confidence`, `gaps`).
- **`run_implement_offline(ctx, *, detail)`** — call `implement_plan` on the confirmed plan, returning the
  suite (`test_data`, `scenarios`, `steps`, `feature`) + a per-artifact **provenance flag** (LLM vs heuristic).

```python
# harness_tpd.py
async def run_define_offline(ctx, *, temp_bank, answers, flags=None):
    with env(flags or {"TPD_RECALL": "0"}):                 # recall OFF for reproducibility (see §11)
        session = PlanSession(temp_bank, ctx, generator=heuristic_or_scripted, restater=make_restater())
        while (open_qs := session.next_questions()) is not None:
            await session.submit(answers.for_round(open_qs))
        result = session.finalize()
    return PlanTrace(plan=result.plan, brief=result.brief, decisions=result.decisions,
                     rounds=list(session.rounds), confidence=result.confidence, gaps=result.open_gaps)

def run_implement_offline(ctx, *, temp_bank, detail=False):
    res = implement_plan(temp_bank, ctx, run_id="eval", now="", detail=detail)
    return SuiteTrace(res, provenance=classify_paths(res))   # LLM (tailored) vs heuristic (_KIND_SUFFIX)
```

---

### T0 — Golden set + trajectory gate · ~2–3 days · no LLM · **PR-required**

**Goal.** Lock the control flow: `define_plan → approve_plan → implement_plan` and the
`methodology → scope → metrics` round order; stand up the golden set with the executed-plan anchor.

1. Author **8–15** `src/test_evaluation/golden_plans/*.json` `PlanEvalCase`s (§7 shapes), including the
   **LUZ-156281 executed plan** as a `reference_executed_plan`; load them with the existing `golden.py` glob.
2. Record `tests/eval/fixtures/packs/<CTX>.json` for each (one-off, committed).
3. Build the TPD harness (`tests/eval/harness_tpd.py`). Reuse the **already-shipped** `test_evaluation.metrics.trajectory`
   unchanged — it is agent-agnostic.
4. `tests/eval/test_eval_tpd_deterministic.py::test_trajectory` — assert
   `trajectory_score(actual, expected, "in_order")==1.0` per golden pack for both the outer tool sequence and
   the inner round order.
5. **CI:** add `pytest tests/eval/test_eval_tpd_deterministic.py` to the existing required deterministic job
   (alongside the KGA `test_eval_deterministic.py`); gate on a clean working tree (`git status --porcelain` empty).

**Done when:** every golden pack passes trajectory 1.0 on a clean tree; a deliberately reordered round turns the
check red.

---

### T1 — Deterministic plan + coverage scores · ~2–3 days · no LLM · **PR-required**

**Goal.** Score *what the plan scoped and the suite covered*, deterministically — the define-brief-scoping and
silent-fallback guards.

1. `metrics/scope_overlap.py` — a near-clone of the shipped `node_overlap.py`, returning a typed `ScopeScore`
   (add to `models.py`) rather than a bare dict:

```python
def scope_scores(scoped: set[str], in_scope: set[str], excluded: set[str] = frozenset()) -> ScopeScore:
    tp = scoped & in_scope
    precision = len(tp) / len(scoped) if scoped else 0.0
    recall    = len(tp) / len(in_scope) if in_scope else 1.0
    return ScopeScore(precision=precision, recall=recall,
                      leaked=sorted(scoped & excluded),   # MUST be empty — the define-brief bug gate
                      missing=sorted(in_scope - scoped))
```

2. `metrics/coverage.py` — AC-coverage recall (behaviours appearing in some scenario `source_refs`) +
   coverage-matrix completeness (per behaviour, required partitions present) + traceability (every scenario
   `source_refs` resolves to a real pack node; every provenance edge resolves):

```python
def coverage_scores(scenarios, behaviours) -> CoverageScore:   # typed result, per_behaviour stays a dict
    covered = {sr for sc in scenarios for sr in sc.source_refs}
    ac_recall = len({b["id"] for b in behaviours} & covered) / len(behaviours) if behaviours else 1.0
    matrix = {}
    for b in behaviours:
        got  = {sc.kind for sc in scenarios if b["id"] in sc.source_refs}
        need = set(b["expected_partitions"])
        matrix[b["id"]] = len(got & need) / len(need) if need else 1.0
    completeness = sum(matrix.values()) / len(matrix) if matrix else 1.0
    return CoverageScore(ac_recall=ac_recall, matrix_completeness=completeness, per_behaviour=matrix)
```

3. `metrics/placeholders.py` — assert no `<generated>`/`<expected>`/`<test-tenant>`/`PASS_METRIC` survives a
   `detail=True` run, every `data_refs` resolves, every step `expected` is non-empty; and assert the
   **provenance flag** is "LLM" on a `detail` run (catches the silent fallback). Return a typed
   `PlaceholderReport` (`passed`, `leaked_tokens`).
4. Add per-pack thresholds to the `PlanEvalCase` (`min_ac_recall`, `min_scope_precision`, defaults `0.8`/`0.8`,
   as fields on the dataclass); **assert `leaked == []` hard**.
5. Fold into `test_eval_tpd_deterministic.py`; still a required PR check.

**Done when:** the excluded-nodes pack fails on `leaked != []` when run against today's brief writer; the
silent-fallback pack (LLM forced to truncate) drops `ac_recall` below the bar; both go green when the bugs are
fixed.

---

### T2 — Groundedness + oracle judging · ~1 week · LLM · **nightly / `eval:`**

**Goal.** Score the brief's groundedness and the steps' oracle strength.

1. The `[eval]` extra (ragas / pandas / datasets / google-adk) **already exists** in `pyproject.toml`; reuse
   the shipped `test_evaluation.metrics.ragas_judge` (its `available()` gate + typed `RagasScore`) verbatim.
2. `metrics/groundedness.py` — RAGAS Faithfulness + Response Relevancy over `{pack subject, brief,
   note synopses, reference brief}`; optionally ADK `hallucinations_v1` via `google-adk` for a second opinion.
3. `metrics/oracle.py` — an LLM classifier tagging each step's `expected` as weak/medium/strong against the
   golden `pass_criteria`; report the distribution and a mean oracle-strength score (typed `OracleScore`).
4. **Non-determinism:** `num_samples≥3`, compare the **mean** to the last main-branch baseline, gate on a
   delta band (fail if faithfulness or oracle-strength drops `>0.05`).
5. `test_eval_tpd_judged.py`; runs on schedule + the `eval:` label; posts scores + TPS as a PR comment.
   Split it like the shipped KGA judged tier: the LLM metrics skip without the extra, the deterministic parts
   always run.

**Done when:** nightly reports faithfulness + oracle strength per pack with a baseline; an injected ungrounded
scope line drops faithfulness below the band; flattening all oracles to `assert 200` drops oracle strength.

---

### T3 — Scenario quality + execution-depth · ~1 week · LLM · **nightly**

**Goal.** The three things set-overlap can't see: redundancy, Gherkin quality, and execution **depth**.

1. `metrics/gherkin_lint.py` — parse the exported `.feature`; assert tag hygiene (`@kind @methodology` on every
   Scenario), one-behaviour-per-scenario, declarative phrasing (LLM), no conjunctive `When`.
2. Redundancy — deterministic `(source_ref, kind)` uniqueness first; LLM semantic near-duplicate pass second.
3. **Execution-depth rubric** — the key metric: LLM-judge each scenario/step for whether it names a
   **concrete, resolvable** endpoint/state (e.g. `CREDIT_CARD_CHARGED_PENDING`, a real path) vs a placeholder
   ("the API request is sent"), benchmarked against the `reference_executed_plan`. This turns the
   codegraph-structure-vs-execution-depth gap into a number.

**Done when:** the LUZ-159312 code-grounded plan scores *measurably lower* execution-depth than the LUZ-156281
executed plan; the metric can tell a plausible-but-shallow suite from an execution-ready one.

---

### T4 — Real mutation + TPS dashboard · gated on Pillar 2, then ongoing · LLM

**Goal.** Swap the fault-detection proxy for real mutation once the scenarios can run, and turn the scatter of
per-surface scores into one trend number with domain-specific gates.

1. **Blocked on the execution stage** ([`RESEARCH-test-executor-agent.md`](./RESEARCH-test-executor-agent.md)
   Pillar 2). When runnable: wire **PIT** against the SUT, compute mutation score per suite, and replace the
   `oracle-strength + fault-class-coverage` proxy in the TPS FaultDetection term.
2. `metrics/tps.py` — the weighted composite (§6), a direct copy of the shipped `pqs.py` shape: `WEIGHTS`
   keys == the `TPSComponents` field names, and `tps()` returns a typed `TPSResult` that **always carries its
   components**.

```python
WEIGHTS = {"fault_detection": .30, "brief_groundedness": .25,
           "coverage": .20, "oracle_strength": .15, "trajectory": .10}
def tps(components: TPSComponents) -> TPSResult:
    score = sum(w * getattr(components, k) for k, w in WEIGHTS.items())
    return TPSResult(tps=round(score, 3), components=components)
```

3. **Rubric-based gates** — each real incident becomes a permanent rule (ADK
   `rubric_based_final_response_quality_v1` / RAGAS `RubricsScore`):

| Rubric | Catches | Ties to |
|---|---|---|
| Scope excludes the excluded nodes | the define-brief-scoping bug | Scope Precision |
| Every behaviour has its required partitions | happy-only silent narrowing | Coverage-Matrix Completeness |
| Every step asserts an end-state, not a status code | shallow oracles | Oracle Strength |
| No placeholder tokens in a detail run | silent heuristic fallback | placeholder-leak |
| Confidence matches the open-gap count | false "high confidence" | confidence honesty |

4. **Dashboard / trend / alerting** — reuse the shipped `test_evaluation.metrics.history` primitive
   (`append_run` / `load_history` / `regressed`, already clock-free — the runner stamps `timestamp`/`commit`,
   not the eval code) against a `memory/eval/tpd-history.jsonl`; render a TPS-over-time trend with
   per-component sparklines; alert on a main-branch TPS drop `>0.05`, **naming the offending component** via the
   repo's Telegram hooks.

**Done when:** a TPS trend line exists with per-component breakdown; real mutation score has replaced the proxy
in the FaultDetection term; and a regression on any surface trips an alert naming the component.

---

### Sequencing & effort — **as re-pointed**

Nothing on the TPD side is built yet; the table below is the plan against the *existing* eval agent, with the
"reuse" column naming what already ships in `src/test_evaluation/`.

| Phase | Depends on | LLM? | Gate | Reuses (shipped) |
|---|---|---|---|---|
| T0 trajectory | — | no | PR-required | `metrics/trajectory.py`, `golden.py`, harness pattern |
| T1 scope + coverage | T0 | no | PR-required | `models.py` dataclass rule, `node_overlap.py` (template for `scope_overlap.py`) |
| T2 groundedness + oracle | T0 + define/implement drivers | yes | nightly | `metrics/ragas_judge.py`, the `[eval]` extra |
| T3 scenario quality + exec-depth | T2 | yes | nightly | — (new) |
| T4 mutation + TPS dashboard | **execution stage (Pillar 2)** + T2/T3 | yes | dashboard | `metrics/pqs.py` (template for `tps.py`), `metrics/history.py`, `metrics/rubrics.py` |

Ship T0+T1 first — deterministic, cheap, and alone they catch the define-brief-scoping bug **and** the silent
fallback. T4 stays **blocked** on the missing execution stage. Because the eval agent already exists, most of
T0/T2/T4's machinery is *reuse*, not new build — the genuinely new code is the scope/coverage/oracle/gherkin
metrics and the two offline drivers.
