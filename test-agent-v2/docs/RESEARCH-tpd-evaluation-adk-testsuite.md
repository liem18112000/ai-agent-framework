# Evaluating the Test-Plan-Definition Agent — a 3-layer framework (ADK + test-suite adequacy)

> **Structure update (2026-09-15):** the two golden sets are now ONE unified dataset — `golden/<seed>.json` with nested `pack` / `plan` view sub-objects (the loaders `load_golden()` / `load_golden_plans()` / `load_canaries()` / `load_canary_plans()` project each view; `golden_plans/` has been removed, canaries stay under `golden/canary/`). The scorers moved into an **`engine/` package** — `engine/pack.py::evaluate_pack`, `engine/plan.py::evaluate_plan`, and `engine/loaders.py` (shared pack/plan loading), re-exported from `test_evaluation.engine`. Path references below that say `golden_plans/`, `engine.py`, or `plan_engine.py` describe the pre-merge layout.


**Purpose.** The sibling report [`RESEARCH-kga-evaluation-adk-ragas.md`](./RESEARCH-kga-evaluation-adk-ragas.md)
answers *"given a seed ticket, how do we know the **pack** the KGA assembled is good?"* This one is its
downstream twin: *given an approved insight pack, how do we know the **test plan** the second agent — the
**Test-Plan-Definition Agent (TPD)** — defined and implemented is good?* Same goal, different artifact. Every
future change to the TPD (the define interrogation, the coverage matrix, the Claude-on-Vertex scenario/step
generators, the prose brief, the self-learning hooks) should be judged against a **repeatable score** instead
of a hand-wave — so a regression is caught by a number, not a human eyeballing a `.feature` file.

It uses the same **three-layer evaluation framework** as the KGA report — measure the *artifact*, the *process*
that produced it, and its *downstream effect* — and fills each layer from two sources:

1. **Google ADK Evaluation** (**Layer 2 — process**) — the same agent-eval harness the KGA report adopts,
   reused because the TPD is *also* an ADK agent. ADK scores the **trajectory** (`define_plan → approve_plan →
   implement_plan`, and the inner `methodology → scope → metrics` round order) and the **final response** (is
   the brief correct, grounded, safe). RAGAS's **generation** metrics fold in here as the same-intent
   cross-check for "is the plan brief grounded in the pack?".
2. **Test-suite adequacy & quality** (**Layer 1 — artifact**, and **Layer 3 — downstream**) — the body of
   software-testing science that answers *"is this a good test suite?"*: **coverage adequacy** (AC traceability,
   equivalence-partition + boundary coverage — ISTQB / ISO-IEC-IEEE 29119), **oracle strength** (does a scenario
   assert an end-state or just a status code?), and **BDD/Gherkin quality** — all measurable on the artifact
   (Layer 1); plus **fault-detection adequacy** (mutation score — Jia & Harman; PIT on the JVM) which needs the
   suite to actually *run*, so it is the **Layer-3** downstream signal, gated on the execution stage.

> **Diagram (open in Excalidraw, PNG renders inline):**
> - The TPD measurement plane — [`tpd-evaluation-adk-testsuite.excalidraw`](./tpd-evaluation-adk-testsuite.excalidraw) · [`.png`](./tpd-evaluation-adk-testsuite.png)

> ⚠️ **Honesty note.** The deepest metric here — **mutation score / real fault detection** — needs the
> scenarios to actually *run* against the system under test. That execution stage does **not exist yet**; it is
> Pillar 2 of [`RESEARCH-test-executor-agent.md`](./RESEARCH-test-executor-agent.md). Until it ships,
> fault detection is measured by a **deterministic proxy** (fault-class coverage + oracle strength), and the
> report says so at every step. Where a claim comes from a single vendor blog rather than a primary standard,
> it is marked *(unverified)*.

> ✅ **Status (2026-09-15): IMPLEMENTED into the ADK-native eval agent.** The TPD scorer is a second engine
> inside [`src/test_evaluation/`](../src/test_evaluation/) — **`plan_engine.py::evaluate_plan(bank, context_id,
> case, *, detail=False) -> PlanReport`**, peer to `evaluate_pack`. Deterministic metrics: `metrics/coverage.py`,
> `oracle.py`, `placeholders.py`, `mutation.py` (fault-class proxy), `tps.py`, and `gherkin_lint.py`. It
> **reuses** the shipped `node_overlap.retrieval_scores` for **scope** (there is no `scope_overlap.py`) and
> `rubrics` for the brief, plus `ragas_judge` / `history` / `trajectory`. Typed models (`PlanEvalCase`,
> `CoverageScore`, `OracleScore`, `PlaceholderReport`, `GherkinReport`, `FaultClassScore`,
> `TPSComponents`/`TPSResult`, `PlanReport`) live in `models.py`; scope reuses `RetrievalScore`. 3 golden plans
> (`golden_plans/plan_{rich,bleed,thin}.json`), the `evaluate_plan` MCP tool on the single gateway, and a
> test-side harness (`tests/eval/harness_tpd.py`) driving the real `gather → refine → define → implement`
> in-process. The LLM tiers (RAGAS brief faithfulness, LLM oracle depth) are wired but **provider-sourced (I8)**
> and gated; the mutation lane (Layer 3 / T4) stays blocked on the execution stage — only the fault-class
> **proxy** ships. `test_evaluation` **never imports `test_plan_definition`**: `evaluate_plan` reads the
> persisted plan/suite as plain JSON via the bank.

---

## 0. TL;DR — the framework, the gap, the principle

**The framework.** A suite can *look* comprehensive and still catch no bugs, so we measure it on three layers
(the [agentic-QA evaluation spec](./agentic-qa-eval-framework.html)):

| Layer | What it measures | TPD question | Lens |
|---|---|---|---|
| **Layer 1 — Artifact** | the plan + suite | scope grounded; every behaviour + partition covered; oracles that discriminate? | **test-suite adequacy** |
| **Layer 2 — Process** | how it got there | right `define→approve→implement` path + rounds; goal achieved? | **ADK** trajectory + tool-use |
| **Layer 3 — Downstream** | the real signal | would the suite actually *kill* a bug in the running system? | **mutation score** (gated on execution) |

**Where we are.** There was **zero automated quality evaluation of the plan** — unit tests for wiring, but
nothing scored *the plan a define produces* or *the suite an implement produces*. Every real TPD defect was
found by a human comparing artifacts by hand:

- the **define brief that ignores both the answers and the pack** (it auto-scoped LUZ-159312 to the *excluded*
  nodes and said "nothing out of scope" — the inverse of the approved understanding);
- the **silent heuristic fallback** that shipped 3 of 6+ behaviours when the LLM JSON truncated (looked full,
  was half-empty);
- the **execution-depth gap** — a codegraph-grounded plan with real *structure* but placeholder oracles,
  benchmarked against a human-authored, *executed* plan (~83 cases, real endpoints/states) that was far stronger;
- the **empty interrogation** ("high confidence", 0 questions) on a rich pack.

Every one is a **quality** failure a metric catches; none is a crash a unit test catches.

**The gap — now closed for Layers 1–2.** We can now answer *"did this change make the plan better or worse?"*
on the artifact and the process; the Layer-3 downstream signal (real mutation) stays blocked on the execution
stage and runs as a proxy until then.

**The principle.**

> **Grade the plan by what it would catch, not by how much it produced.** A test-plan agent is a *judgement*
> engine (the brief) feeding a *generative* engine (the scenarios/steps/data). A big suite that misses the real
> failure modes is worse than a small one that catches them — so score **coverage of behaviours and faults**,
> not scenario count. Anchor every score to a small human-curated golden set of pack → reference-plan pairs —
> and where one exists, to a **human-authored, executed** plan as the ground truth. Keep deliberately-bad
> **canary packs** that must always score low.

![The TPD measurement plane. Bottom: the TPD pipeline (Insight PACK → DEFINE methodology·scope·metrics rounds → approve → TestPlan BRIEF → IMPLEMENT coverage matrix → Scenarios/Steps + Test-data → .feature Gherkin export). Three measurement layers: Layer 1 (test-suite adequacy — scope groundedness, AC-coverage recall × matrix completeness, oracle strength, fault-class coverage, gherkin lint, placeholder validity), Layer 2 (ADK trajectory over define→approve→implement + round order), Layer 3 (downstream — real mutation score, gated on the execution stage). A single human-curated golden set anchored to a REAL executed plan (LUZ-156281) plus canary packs is the ground truth. The families combine into one weighted Test-Plan Score (TPS), consumed by three lanes: a deterministic PR gate, an LLM-judged nightly run, and the mutation lane blocked on execution.](./tpd-evaluation-adk-testsuite.png)

---

## 1. The three-layer framework (the organizing spine)

Same spine as the KGA report, applied to a *plan + suite*:

- **Layer 1 — Artifact quality (the plan + suite).** Everything about the output itself, all measurable
  **without running anything**: is the brief's **scope** grounded in the pack (no invented or excluded nodes);
  does the scenario set **cover** every in-scope behaviour and its negative/boundary/error partitions with real
  **traceability**; would a scenario **discriminate** — a real end-state oracle, not `assert 200`; are the
  artifacts **real** (no placeholder leak) and the Gherkin **well-formed**. This is test-suite adequacy science
  and it carries the heaviest TPS weight.
- **Layer 2 — Agent process (how it got there).** The controller: the `define→approve→implement` trajectory,
  the `methodology→scope→metrics` round order, interrogation yield, goal accuracy. ADK's lens.
- **Layer 3 — Downstream effectiveness (the real signal).** Whether the suite actually *kills bugs* in the
  running system: **mutation score** (inject faults, count kills), defect-detection rate vs baseline, and human
  acceptance (cases kept vs edited vs deleted). All need the suite to *run* → **gated on the execution stage**
  (Pillar 2). Until then, Layer 3 is a proxy: oracle strength + fault-class coverage stand in for mutation.

Every metric below is tagged with its layer. The TPS composite spans Layers 1–2; the `fault_detection` term is
the Layer-1 **proxy** today (oracle + fault-class coverage) and becomes the Layer-3 **real mutation** score once
the execution stage lands.

---

## 2. Concepts & terms (glossary)

- **Plan / TestPlan** — the Stage-A artifact for one `context_id`: structured `methodology`, `scope`,
  `out_of_scope`, `metrics` (what "passed" means), `confidence`, `source_refs`, `status`, plus a human-facing
  **brief**. Persisted to the bank at `test-plan/<ctx>/plan.json` + `plan-brief.md`.
- **Suite** — the Stage-B artifacts: `TestData`, `TestScenario`s, `TestStep`s, and the exported Gherkin
  `.feature`. Persisted at `test-plan/<ctx>/{scenarios,steps,test-data}.json`.
- **Coverage matrix** — per in-scope behaviour, the scenario **kinds** the agent generates:
  `_FULL_MATRIX = ["happy","negative","boundary","error"]` (the eval-side partition model in `plan_engine.py`),
  downgraded to happy-only when a metric string literally says "happy only". The equivalence-partitioning +
  boundary-value-analysis surface.
- **Behaviour / AC** — one acceptance-criterion proxy in the pack: a **grounded note** (`pack.grounded`).
  Scenarios are generated one-per-behaviour × the matrix, each carrying `source_refs=[note.id]` back to the
  behaviour it covers. When the golden case omits `behaviours`, the engine derives them from `pack.grounded`
  with the full partition matrix.
- **Traceability** — the bidirectional link AC↔scenario. Forward: does every in-scope AC have a scenario?
  Backward: does every scenario cite a real pack node? `coverage_scores` computes it as
  `1 − untraceable/total` (a scenario is untraceable when none of its `source_refs` is in the real pack id set).
- **Oracle** — what a scenario *asserts*. A **strong** oracle verifies a concrete end-state; a **weak** one
  asserts only a status code / "accepted". Oracle strength is the difference between a test that catches a
  regression and one that always passes.
- **Golden set / plan-evalset** — a human-curated set of `(pack, reference_plan)` cases; the ground truth every
  metric scores against. The star anchor is a **human-authored, executed** plan (LUZ-156281).
- **Canary pack** — a deliberately-bad golden pack (a bled brief, a thin pack) whose TPS *must* stay low; a
  canary scoring high means the metric or judge is broken, not the agent (§11 calibration).
- **Mutation score** — fraction of injected faults (mutants) the suite would **kill**. The gold standard for
  fault-detection adequacy; needs runnable tests → the Layer-3 signal, gated on the execution stage.
- **Deterministic vs judged** — deterministic metrics are computed by code over ids/sets/structure → cheap,
  stable, PR-gate-able. Judged metrics prompt the **provider-sourced** LLM (faithfulness, oracle depth) →
  non-deterministic, sampled, nightly.

---

## 3. The TPD as an evaluation target

The TPD is **two engines** in series, and they demand different metrics:

- a **judgement engine** (Stage A / define) — an interrogation (`methodology → scope → metrics`) that distills
  human calls into a structured plan. Output: *decisions* + a *brief*. Score it for groundedness, scope
  correctness, honest confidence.
- a **generation engine** (Stage B / implement) — expansion of the confirmed plan into a suite. Output:
  *scenarios/steps/data*. Score it for coverage, traceability, oracle strength, and (eventually) fault detection.

Pin down deterministic vs stochastic stages — ADK's `tool_trajectory_avg_score` defaults to a hard **1.0**,
only legitimate on the deterministic skeleton:

| Stage | Deterministic? | Engine | Layer | Notes |
|---|---|---|---|---|
| Round order `methodology→scope→metrics` | ✅ | Judgement | 2 | fixed dependency order |
| Question generation per round | ⚠️ LLM-or-heuristic | Judgement | 2 | falls back to heuristic on empty — *which path?* |
| Decision distillation | ✅ | Judgement | 2 | human→decision(high); self→assumption(low) |
| Plan assembly (scope/method/metrics) | ✅ | Judgement | 1 | from decision rounds |
| Confidence | ✅ | Judgement | 1 | opens→low; assumption→medium; else high |
| Prose brief | ⚠️ LLM-or-heuristic | Judgement | 1 | the headline "answer" of Stage A |
| Test-data generation | ⚠️ | Generation | 1 | placeholders `<generated>`/`<expected>` in heuristic |
| Scenario generation | ⚠️ LLM-or-heuristic | Generation | 1 | matrix per behaviour; **silent fallback risk** |
| Step generation | ⚠️ | Generation | 1 | Given/When/Then |
| Gherkin export | ✅ | Generation | 1 | tags `@kind @methodology` |
| Provenance edges | ✅ | Generation | 1 | scenario→insight edges (traceability) |

**The single most important consequence:** the Stage-A brief and the Stage-B scenarios each have a *heuristic*
path and an *LLM* path, and the code **silently** falls back heuristic→ when the LLM returns nothing or
truncates. So **every content metric records which path produced the artifact** — a tailored title means the LLM
ran; a kind-suffix string ("— happy path") means the heuristic ran (`placeholders.py` sets `provenance`). A
truncated-JSON fallback that drops half the behaviours is otherwise invisible. This is the TPD analog of the
KGA's "two retrievers" twist.

---

## 4. Layer 1 — Artifact quality (the plan + suite) · test-suite adequacy

This is the heart of the report — the lens the KGA did not need. A test-plan agent must be judged the way any
test suite is judged. Five families, all measurable **without running anything**, feeding the TPS.

> **Diagram:** Layer 1 in detail — [`tpd-layer1-artifact-testsuite.excalidraw`](./tpd-layer1-artifact-testsuite.excalidraw) · [`.png`](./tpd-layer1-artifact-testsuite.png)

![Layer 1 (Artifact quality · test-suite adequacy), blue. The plan+suite artifact sits at the center (brief + scenarios/steps/test-data + .feature), ringed by six adequacy families that each "measure" it and converge into the TPS: brief groundedness (scope precision/recall reusing retrieval_scores + rubrics + Faithfulness), coverage adequacy (ac_recall × matrix_completeness + traceability), oracle strength (weak/medium/strong), executability/placeholder validity, Gherkin lint, and the fault-class-coverage proxy. Bottom: the TPS = 0.30·fault_detection + 0.25·brief_groundedness + 0.20·coverage + 0.15·oracle_strength + 0.10·trajectory chip.](./tpd-layer1-artifact-testsuite.png)

### 4.1 Brief groundedness — is the scope true to the pack?

The brief is the known-broken surface (it once auto-scoped to the *excluded* nodes). Score it two ways, then
average:

| Metric | Definition | Kind | TPD mapping |
|---|---|---|---|
| **Scope Precision / Recall** | overlap of `plan.scope` with the golden in-scope ids | **Det.** (set overlap) | reuses `node_overlap.retrieval_scores(scoped, in_scope, must_not_scope)` — **no separate `scope_overlap.py`**. |
| **`must_not_scope` leak gate** | did the scope include any excluded id? | **Det.** | the define-brief-scoping bug guard — *any* appearance is a hard fail (`scope.leaked`). |
| **Brief fabrication rubrics** | brief cites only real ids / no invented URLs | **Det.** (regex + set) | reuses `rubrics.cites_only_real_ids` / `no_invented_urls` over the brief. |
| **Faithfulness / `hallucinations_v1`** | fraction of brief claims supported by the pack | **Judge** | RAGAS/ADK second opinion; provider-sourced. |
| **Response Relevancy** | does the brief address *this pack's* subject | **Judge** | RAGAS. |

As built, the TPS `brief_groundedness` term is `round((brief_ok + scope.precision) / 2, 3)`, where `brief_ok`
is the two fabrication rubrics both passing (`0.0/1.0`). Faithfulness/relevancy are the nightly judged
cross-check, not part of the deterministic composite.

### 4.2 Coverage adequacy — did the suite cover the behaviours and their partitions?

| Metric | Definition | Kind | TPD mapping |
|---|---|---|---|
| **AC-Coverage Recall** | of the in-scope behaviours, how many have ≥1 scenario tracing to them | **Det.** | grounded notes appearing in some scenario's `source_refs`. **Catches the silent-fallback drop** (3 of 6 → 0.5). |
| **Coverage-Matrix Completeness** | of the required partitions per behaviour, how many are present | **Det.** | for each behaviour, are `happy/negative/boundary/error` scenarios present? Scores `_FULL_MATRIX` vs what shipped. |
| **Traceability** | every scenario resolves to a real pack node | **Det.** | `1 − untraceable/total` (a scenario is untraceable when no `source_ref` is a real pack id). |

As built, `metrics/coverage.py::coverage_scores(scenarios, behaviours, valid_refs=pack_ids)` returns a typed
`CoverageScore(ac_recall, matrix_completeness, traceability, per_behaviour, uncovered, untraceable)`. The TPS
`coverage` term is `round(cov.ac_recall × cov.matrix_completeness, 3)` — **traceability is reported but not
folded into the composite** (it surfaces `untraceable` scenarios for the report, and is a natural gate to add).
Coverage-Matrix Completeness is the equivalence-partitioning measure made concrete: the partition set **is** the
matrix, so we score against it directly, and it catches the brittle happy-only downgrade by checking *actual
partition presence*, not the metric string.

### 4.3 Oracle strength — would a scenario discriminate?

A test that asserts only `2xx` kills almost no mutant; a test that asserts a real end-state kills many.
`metrics/oracle.py::oracle_strength(steps, pass_criteria)` classifies each step's `expected`:

- **strong (1.0)** — names a concrete, resolvable end-state: an enum-shaped token (`[A-Z][A-Z0-9_]{3,}`, e.g.
  `CREDIT_CARD_CHARGED_PENDING`) or a match against the plan's `pass_criteria`;
- **weak (0.0)** — asserts only a status code / "accepted" / "succeeds" / "is processed" (the `_WEAK` list);
- **medium (0.5)** — anything in between.

It returns a typed `OracleScore(score, distribution, weak)` — the mean weight, the strong/medium/weak counts,
and the weak assertions to fix. Measurable *without running anything* and a strong predictor of mutation score;
it directly encodes the **execution-depth gap**.

### 4.4 Executability / validity — are the artifacts real or placeholders?

`metrics/placeholders.py::placeholder_scan(scenarios, steps, test_data, *, detail)` is the validity gate. It
scans for `<generated>` / `<expected>` / `<test-tenant>` / `PASS_METRIC` and infers **provenance** (heuristic if
a kind-suffix title is present, else llm). On a `detail=True` run, a leaked token **or** heuristic provenance
fails it — that is the silent-fallback catch (a `detail` run that shipped heuristic artifacts). Returns a typed
`PlaceholderReport(passed, leaked_tokens, provenance)`.

### 4.5 BDD / Gherkin quality — is the `.feature` well-formed?

`metrics/gherkin_lint.py::gherkin_lint(feature_text)` returns a typed `GherkinReport(passed, scenarios, tagged,
issues)`: it asserts a `Feature:` header, that every `Scenario:` carries **≥2 tags** (`@kind @methodology`),
and that Given/When/Then steps are present. (It is scored in the judged/quality tier; `evaluate_plan` leaves
`PlanReport.gherkin` `None` unless wired in — the lint runs in `test_eval_tpd_*` over the exported feature.)
Redundancy — `(source_ref, kind)` uniqueness first (the heuristic guarantees it; the LLM path can duplicate),
semantic near-duplicate detection second — is the minimality companion.

### 4.6 The composite — Test-Plan Score (TPS)

One weighted mean for dashboards (`metrics/tps.py`), weighting the **silent-failure** surfaces highest:

```
TPS = 0.30·fault_detection      # oracle+fault-class proxy now; real mutation once executable (Layer 3)
    + 0.25·brief_groundedness   # (brief_ok + scope.precision) / 2
    + 0.20·coverage             # ac_recall × matrix_completeness
    + 0.15·oracle_strength      # mean oracle weight over the steps
    + 0.10·trajectory           # fixed 1.0 at runtime (the harness scores the real trace)
```

As built, `evaluate_plan` fills `TPSComponents`: `fault_detection = fault.coverage` (the fault-class proxy),
`brief_groundedness`, `coverage`, `oracle_strength = orc.score`, and `trajectory = 1.0` (neutral — the tier
trace lives in the offline harness / ADK runner, not the runtime path). **Always emit the components** next to
the number: a 0.04 TPS drop could be all oracle-strength or all coverage. While mutation is a proxy,
`fault_detection` and `oracle_strength` measure the same thing at different fidelities — re-split once real
mutation lands (§4.7 / Layer 3).

### 4.7 Fault-detection *proxy* (fault-class coverage) — the Layer-1 stand-in for Layer-3 mutation

`metrics/mutation.py::fault_class_coverage(scenarios, behaviours)` is the honest proxy until the execution stage
exists. Each behaviour lists its **known fault classes** in the golden set (e.g. "retry fires on the wrong
`failCount` day", "QR fallback wrongly removed for a COMPANY tenant"); a class counts as *aimed-at* when some
**non-happy** scenario `source_refs` the behaviour. Returns `FaultClassScore(coverage, covered, missing)`. It is
a checklist stand-in for mutation — measurable now, and the term real mutation replaces in Layer 3.

---

## 5. Layer 2 — Agent process · Google ADK Evaluation

Layer 2 scores the controller, not the plan. Since the ADK-native cutover the TPD **is** an ADK agent, so ADK's
own harness (the `eval/` subpackage, §8.2) applies directly, alongside our deterministic trajectory metric.

> **Diagram:** Layer 2 in detail — [`tpd-layer2-process-adk.excalidraw`](./tpd-layer2-process-adk.excalidraw) · [`.png`](./tpd-layer2-process-adk.png)

![Layer 2 (Agent process · Google ADK), amber. Section A: the trajectory being scored — the outer define_plan → approve_plan → implement_plan sequence (in_order) with the inner methodology → scope → metrics round order, and the trajectory_score(actual, expected, mode) chip. Section B: the ADK metrics — deterministic (tool_trajectory_avg_score=1.0, response_match_score ROUGE 0.35), judged (hallucinations_v1, final_response_match_v2, rubric_based_final_response_quality_v1), and binary labels (Interrogation Yield, Agent Goal Accuracy). Section C: the ADK-native runner — golden_plans/*.json → plan_eval_set() → EvalSet/EvalCase → run_judged_eval (AgentEvaluator) → EvalConfig criteria, with PLAN_METRICS (tps_score 0.70 + must_not_scope_leak 1.0) and the provider-sourced judge (I8).](./tpd-layer2-process-adk.png)

### 5.1 The data model (reused)

ADK structures eval as **EvalSet → EvalCase → Invocation**. One EvalCase records, for one pack: the input
(`define <ctx>` … the answer sequence … `approve_plan` … `implement_plan`), the **expected tool-use
trajectory**, and the **reference plan/brief**. We reuse the KGA harness's schema verbatim so both agents share
one eval codebase; `eval/evalset.py` emits `tpd_plan.evalset.json` from `golden_plans/`.

### 5.2 The metrics that apply to the TPD

| ADK config key | Measures | TPD mapping | Value |
|---|---|---|---|
| `tool_trajectory_avg_score` | exact match of the tool-call sequence | outer `define_plan → approve_plan → implement_plan`; inner `methodology → scope → metrics` | **HIGH** — deterministic, regression-prone |
| `hallucinations_v1` | each response sentence grounded in the context | is every claim in the **brief** traceable to a pack note? | **CRITICAL** (Layer-1 cross-check) |
| `final_response_match_v2` | LLM-judged semantic match to a reference | brief vs a **reference brief** (paraphrastic — beats ROUGE) | HIGH for the brief |
| `response_match_score` | ROUGE-1 overlap vs reference | only the deterministic summary line | LIMITED |
| `rubric_based_final_response_quality_v1` | LLM-judged quality against custom rubrics | the TPD-specific rubrics in §8.3 | **HIGH, later** |

As built, `eval/config.py` declares `PLAN_METRICS` = `tps_score` (threshold 0.70, our TPS as a custom metric) +
`must_not_scope_leak` (threshold 1.0, the scope-leak gate as a custom metric), and the shared judged tier
(`JUDGED_METRICS` at 0.70). Interrogation Yield (≥1 open question on a rich pack) and Agent Goal Accuracy
(confirmed, on-scope, non-empty suite) are the Layer-2 binary labels.

### 5.3 Deterministic trajectory

Our own `metrics/trajectory.py::trajectory_score` (agent-agnostic, shared with the KGA) scores the outer tool
sequence and the inner round order `in_order` from the harness-derived trace. This is the deterministic PR gate
on the TPD control flow — a reordered round turns it red.

---

## 6. Layer 3 — Downstream effectiveness (gated on execution)

This is the truest layer and the one that separates a *plausible* suite from an *effective* one — and it is the
one that isn't fully built, because it needs the suite to *run*.

> **Diagram:** Layer 3 in detail — [`tpd-layer3-downstream.excalidraw`](./tpd-layer3-downstream.excalidraw) · [`.png`](./tpd-layer3-downstream.png)

![Layer 3 (Downstream effectiveness · gated), green + dashed. A prominent GATED banner: needs the not-yet-built execution stage (RESEARCH-test-executor-agent.md, Pillar 2). Behind the gate, four unavailable signals: Mutation Score (PIT/pitest, the gold standard), Defect-detection rate vs baseline, Human acceptance, Escaped defects. The key argument: TODAY fault_detection = the oracle-strength + fault-class-coverage proxy (Layer 1, measurable now) → when the suite can run → THEN fault_detection = real Mutation Score (Layer 3), both feeding the same 0.30·fault_detection TPS term.](./tpd-layer3-downstream.png)

- **Mutation Score (the gold standard).** Inject small faults (mutants) into the system under test and measure
  the fraction the suite **kills**. Established since Jia & Harman; on the JVM (the luz stack is Java) the tool
  is **PIT/pitest**. Requires the scenarios to *run* — the execution stage from
  [`RESEARCH-test-executor-agent.md`](./RESEARCH-test-executor-agent.md) Pillar 2. **Not available today.** When
  it is, mutation score becomes the `fault_detection` term (replacing the §4.7 proxy) and the TPS's heaviest.
- **Defect-detection rate** — bugs found when the plan is executed vs a baseline plan. Also execution-gated.
- **Human acceptance** — of the generated cases, how many a QA lead keeps as-is vs edits vs deletes. A cheap
  downstream proxy that needs no execution but needs a human review loop; not yet instrumented.
- **Escaped defects** — production bugs in areas the plan claimed to cover. The ultimate signal, longest loop.

Until the execution stage lands, Layer 3 is represented by the **oracle strength + fault-class coverage proxy**
(§4.3 / §4.7) — measurable without running anything and a strong *predictor* of mutation score. The report says
so at every step: the `fault_detection` TPS term is a proxy today, and the execution stage is the clean seam
between this report and its sibling — the KGA scores retrieval, this one scores planning, both hand off to the
execution pillar.

---

## 7. The mapping — TPD stage × metric × layer (core deliverable)

"Det." = deterministic (PR gate). "Judge" = LLM-judged (nightly). "Exec" = needs the execution stage (gated).

| TPD stage / artifact | Layer | Primary metric(s) | Kind | Ground truth |
|---|---|---|---|---|
| Outer `define→approve→implement` | 2 | `tool_trajectory_avg_score` (IN_ORDER) | Det. | expected tool list |
| Inner rounds `methodology→scope→metrics` | 2 | `tool_trajectory_avg_score` | Det. | expected round order |
| Interrogation yield | 2 | questions raised / pack-richness + Goal Accuracy | Det.+Judge | ≥1 open question on a rich pack |
| Plan **scope** | 1 | **Scope Precision/Recall** + `must_not_scope` gate | Det. | golden in-scope + excluded ids |
| Plan **brief** groundedness | 1 | fabrication rubrics (Det.) + Faithfulness / `hallucinations_v1` (Judge) | Det.+Judge | — |
| Plan **brief** correctness | 1 | `final_response_match_v2` | Judge | reference brief |
| Plan **confidence** honesty | 1 | rubric: confidence matches open-gap count | Det. | — |
| **Scenarios: AC coverage** | 1 | **AC-Coverage Recall** | Det. | golden behaviours |
| **Scenarios: partitions** | 1 | **Coverage-Matrix Completeness** | Det. | golden partitions per behaviour |
| **Scenarios: precision** | 1 | scope-based; `must_not_scope` gate | Det. | golden in/excluded ids |
| Scenarios: traceability | 1 | `1 − untraceable/total` | Det. | pack id set |
| Steps: oracle | 1 | **Oracle Strength** distribution | Det.+Judge | golden pass-criteria |
| Steps: concreteness | 3 | **execution-depth**: real endpoint/state vs placeholder | Judge | reference executed plan |
| Test-data | 1 | placeholder-leak + provenance | Det. | — |
| Gherkin `.feature` | 1 | BDD/Gherkin lint (tags, structure) | Det. | — |
| **Whole suite: fault detection** | 1→3 | fault-class coverage (proxy now) → **Mutation Score** (real) | Det. → Exec | golden fault classes |
| Whole run | 2 | Agent Goal Accuracy | Judge | binary label |

---

## 8. Engine + harness design — **as built**

Mirror the KGA design (§10 of the sibling): a deployable **scoring engine**, a test-side **offline harness**,
and the **ADK-native runner** — all in the shared `src/test_evaluation/` agent, which already scores the KGA
pack. The TPD half **adds** an `evaluate_plan` engine + the new deterministic metrics, and **reuses** the
shipped `node_overlap` (for scope), `rubrics`, `ragas_judge`, `history`, and `trajectory`.

### 8.1 The scoring engine — `plan_engine.py`

`plan_engine.py::evaluate_plan(bank, context_id, case=None, *, detail=False) -> PlanReport` reads the persisted
plan + suite as plain JSON from `test-plan/<ctx>/` (`plan.json`, `plan-brief.md`, `scenarios.json`, `steps.json`,
`test-data.json`) plus the pack (`load_pack` → `pack_ids`, `pack.grounded`), **without importing
`test_plan_definition`**. It composes the TPS from: `scope = retrieval_scores(plan.scope, in_scope,
must_not_scope)` (reused node-overlap), `cov = coverage_scores(...)`, `orc = oracle_strength(steps,
pass_criteria)`, `fault = fault_class_coverage(...)`, `phold = placeholder_scan(..., detail=detail)`, and the
brief fabrication rubrics. Behaviours default to `pack.grounded` × the full matrix when the golden case omits
them; `pass_criteria` default to `plan.metrics`.

The agent surface is shared: `agent.py::EvaluatorAgent(RouterAgent)` routes `"…plan…"` → `evaluate_plan`, else
`evaluate_pack`; `bridge/mcp_server.py` registers `evaluate_plan(context_id)` on the single gateway. There is
**no `scope_overlap.py`, no `groundedness.py`, no `executor/`, no `server.py`** — those were in the original
sketch and never built; scope reuses `node_overlap`, brief groundedness reuses `rubrics` + `ragas_judge`, and
serving is the shared root `main:app` (`AGENT=test_evaluation`).

### 8.2 Two harness paths — offline harness + ADK-native runner

**(a) `tests/eval/harness_tpd.py`** drives the real `gather → refine → define → implement` in-process (reusing
the KGA `harness.py` to build the pack first), over the same Starlette `TestClient` + JSON-RPC A2A stack, a
`FakeBucket`-backed `MemoryBank`, and scripted answers (no LLM). It reads the same artifacts a human reviews —
`get_plan` for the brief, `get_scenarios` for the suite, the persisted decisions/questions/answers, the run log
— and shares the temp-bank + recorded-fixture discipline (never the prod `GCS_BUCKET`).

```
tests/eval/
  harness_tpd.py                 # run_define_offline / run_implement_offline + PlanTrace
  test_eval_tpd_deterministic.py # T0 trajectory · T1 scope + coverage + placeholder   (PR gate)
  test_eval_tpd_metrics.py       # coverage/oracle/placeholder/gherkin/mutation/tps math (PR gate)
  test_plan_engine.py            # evaluate_plan + the ADK router, end-to-end            (PR gate)
  test_eval_tpd_judged.py        # T2 RAGAS brief · T3 gherkin/oracle · T4 TPS/fault     (nightly)
```

**(b) The ADK-native runner — `src/test_evaluation/eval/`** (shared with the KGA). `eval/adk_metrics.py`
exposes `tps_score` + `must_not_scope_leak` as ADK custom-metric functions; `eval/config.py::PLAN_METRICS`
declares their thresholds; `eval/evalset.py::plan_eval_set()` builds the ADK `EvalSet` from `golden_plans/`; and
`eval/runner.py` drives `AgentEvaluator` with a provider-sourced judged tier (`run_judged_eval`).

### 8.3 The provider-sourced judge (I8)

Identical to the KGA report (§10.3): every judged path — RAGAS brief faithfulness/relevancy, the LLM oracle-depth
classifier, the ADK judged criteria — sources its model from the one configured `ModelProvider`
(Claude-on-Vertex via `agent_model()`), never an OpenAI/Gemini default. `ragas_judge.judge` raises on a `None`
llm; `judged_criteria()` returns `{}` without a provider. So the offline suite touches no network, and the
judged tier runs a pinned, provider-sourced model — the prerequisite for calibration (§11).

### 8.4 Three lanes of run

1. **PR gate (seconds, no LLM, no network).** Drive `run_define_offline` + `run_implement_offline` against a
   recorded pack + temp bank; compute trajectory, scope + `must_not_scope`, AC-coverage recall, matrix
   completeness, traceability, oracle strength, fault-class coverage, placeholder-leak, Gherkin lint, TPS. Fail
   on any golden regression. Required check; gate on a clean tree.
2. **Nightly / `eval:` label (minutes, LLM).** RAGAS Faithfulness / Response Relevancy + `hallucinations_v1` on
   the brief; LLM oracle-depth and execution-depth rubric on the steps. Post **TPS + component deltas** vs the
   last main-branch baseline; sample means, gate on a band. Skips without the `[eval]` extra / creds.
3. **Execution tier (gated on Pillar 2 — Layer 3).** Once the scenarios become runnable, wire real **PIT
   mutation score** against the SUT and swap it into the `fault_detection` term. Until then it computes only the
   fault-class-coverage proxy.

**Determinism & flakiness.** Sample `num_samples≥3`, compare means, gate on a delta band ("oracle-strength
dropped >0.05"), never an absolute single-sample pass/fail. Deterministic metrics gate absolutely.

---

## 9. The golden dataset (plan-evalset) design

Curate **8–15 packs** spanning the shapes that break the TPD. Crucially, the TPD golden set can be **anchored to
a real, executed, human-authored plan** — a ground truth the KGA never had.

| Pack shape | Example | Why it's in the set | Role |
|---|---|---|---|
| Rich, code-grounded pack | LUZ-159312 (luz_finance codegraph) | happy path; high AC-recall + matrix completeness | must-pass |
| **Excluded-nodes pack** | LUZ-159312 w/ siblings/file-import excluded | the define-brief-scoping bug: tests Scope Precision + `must_not_scope` | **canary** (must not leak) |
| **Thin pack** (title only) | any title-only ticket | tests Interrogation Yield + the empty-interrogation false-positive | **canary** |
| Happy-only vs full-matrix | one metrics="happy only", one default | tests Coverage-Matrix Completeness in both modes | must-pass |
| **Human-executed reference** | **LUZ-156281 "Invoice Run Dunning Tests"** (~83 cases, real endpoints/states) | the star anchor: real AC-recall / oracle-strength / execution-depth benchmark | anchor |

Per pack, author a small JSON (the shipped `PlanEvalCase` dataclass in `models.py`):

```json
{
  "seed": "plan_rich",
  "fixture": "plan_rich",
  "shape": "rich-code-grounded",
  "expected_trajectory": ["define_plan", "approve_plan", "implement_plan"],
  "expected_rounds": ["methodology", "scope", "metrics"],
  "in_scope_ids":       ["jira:LUZ-159312", "codegraph:luz_finance/InvoiceRunController"],
  "must_not_scope_ids": ["jira:LUZ-159313", "jira:LUZ-158446"],
  "behaviours": [
    {"id": "jira:LUZ-159312#retry", "expected_partitions": ["happy","negative","boundary","error"],
     "fault_classes": ["retry fires on wrong failCount day", "second-consecutive-fail not detected"]},
    {"id": "jira:LUZ-159312#qr",    "expected_partitions": ["happy","negative"],
     "fault_classes": ["QR fallback removed for COMPANY tenant (should be individual-only)"]}
  ],
  "pass_criteria": ["end-state: tracking row reaches CREDIT_CARD_CHARGED_PENDING"],
  "min_ac_recall": 0.8,
  "min_scope_precision": 0.8,
  "reference_brief": "This plan verifies the dunning retry cadence … in scope … out of scope …"
}
```

Mapping to the metrics (and to the HTML golden-schema vocabulary):

- `in_scope_ids` = the **must-have** cases → Scope Precision/Recall; `must_not_scope_ids` = the HTML schema's
  **known_traps** → the hard-negative gate (any appearance is a hard fail).
- `behaviours[].expected_partitions` → Coverage-Matrix Completeness; `behaviours[].fault_classes` → the
  fault-class-coverage proxy (also **known_traps** — every real bug class becomes a checklist entry).
- `pass_criteria` → the Oracle-Strength target for the steps.
- `reference_brief` (+ the executed-plan anchor) → the depth/recall benchmark, the single most valuable ground
  truth.

Golden packs live in [`src/test_evaluation/golden_plans/*.json`](../src/test_evaluation/golden_plans/) (sibling
of the KGA `golden/`, loaded the same way via `golden.py`); the recorded pack fixtures the harness replays live
under `tests/eval/`. **As built, the seeds are `plan_rich` / `plan_bleed` / `plan_thin`** (the last two double
as canaries); the live LUZ-keyed 8–15 set incl. the LUZ-156281 anchor is the pending coverage work.

---

## 10. What the metrics would have caught (retro-fit to real incidents)

| Incident (from project history) | Layer | Metric that flags it | How |
|---|---|---|---|
| **Define brief ignores answers AND the pack** (auto-scoped LUZ-159312 to excluded subtasks) | 1 | Scope Precision ↓, `must_not_scope` leak, Faithfulness ↓ | the golden pack lists the excluded siblings in `must_not_scope_ids`; scoping them is an instant hard fail; the brief citing them fails faithfulness. |
| **Silent heuristic fallback** (LLM JSON truncated → 3 of 6+ behaviours) | 1 | AC-Coverage Recall ↓, provenance = heuristic | 6 golden behaviours, 3 in `source_refs` → recall 0.5; the shipped titles are kind-suffix strings → provenance "heuristic" contradicts a `detail` run. |
| **Execution-depth gap** (placeholder oracles vs the human plan's real states) | 1 → 3 | Oracle Strength ↓, exec-depth rubric ↓, (later) Mutation Score ↓ | steps asserting `2xx`/`PASS_METRIC` score weak/medium; the executed plan asserts `CREDIT_CARD_CHARGED_PENDING` → strong; fault-class coverage shows the QR-COMPANY class untested. |
| **Empty interrogation** ("high confidence", 0 questions) | 2 | Interrogation Yield ↓, Goal Accuracy = 0 | a rich golden pack expects ≥1 open question; zero is a false-positive smell. |
| **Happy-only silent narrowing** | 1 | Coverage-Matrix Completeness ↓ | the metric checks *actual* partition presence per behaviour, not the `"happy only"` substring. |
| **Placeholder leak on a `detail` run** | 1 | placeholder-leak = fail | deterministic regex; a `detail=True` run that leaks a placeholder has silently fallen back to the heuristic. |

---

## 11. Judge calibration & canary packs

The judged tier (RAGAS brief Faithfulness / Response Relevancy, `hallucinations_v1`, the LLM oracle-depth
classifier) is trustworthy only once the provider-sourced judge is **calibrated against humans**, and the
deliberately-bad **canary packs** (`golden_plans/canary/`) are the cheap drift guard between recalibrations.
The full protocol — Cohen's kappa, the `judge-human >= human-human - 0.1` gate, and the shipped canary
implementation — is its own page: **[`RESEARCH-judge-calibration-kappa.md`](./RESEARCH-judge-calibration-kappa.md)**.

In short: keep a dimension **judged** only if the judge agrees with a human about as well as two humans agree
with each other; otherwise keep it **deterministic** (which is why most of the TPS is set-overlap + partition
presence). Pin the judge model and re-calibrate on any model/prompt change.

## 12. Phased roadmap — **shipped (Layers 1–2), Layer 3 gated**

Cheap deterministic value first; expensive LLM judging next; real fault detection last (it depends on a stage
that isn't built). Same T-naming as the KGA report's E-phases so the two roadmaps read as one program.

- **T0 — Golden set + trajectory (no LLM). ✅** `golden_plans/*.json` + `metrics/trajectory.py` (reused) score
  `define→approve→implement` + round order as a **required PR check** (Layer 2). The LUZ-156281 executed-plan
  anchor is pending coverage.
- **T1 — Deterministic plan + coverage scores (no LLM). ✅** Scope Precision/Recall + the `must_not_scope` gate
  (reused `node_overlap`, **catches the define-brief-scoping bug**); AC-Coverage Recall + Matrix Completeness +
  Traceability (`coverage.py`, **catches the silent fallback + happy-only narrowing**); Oracle Strength
  (`oracle.py`); placeholder-leak + provenance (`placeholders.py`). All Layer 1, all PR gate.
- **T2 — Groundedness + oracle judging (LLM, nightly). ✅ gated.** RAGAS Faithfulness + Response Relevancy +
  `hallucinations_v1` over the brief; LLM oracle-depth over the steps — provider-sourced, skips without
  `[eval]`/creds (Layer 1).
- **T3 — Scenario quality + execution-depth (LLM, nightly). ◑** Gherkin lint (`gherkin_lint.py`, shipped) +
  redundancy + the **execution-depth rubric** benchmarked against the reference executed plan. The
  code-grounded-vs-executed gap becomes a number (Layer 1 → 3 boundary).
- **T4 — Real mutation + TPS dashboard (gated on Pillar 2). ◔** `metrics/tps.py` (shipped) + the fault-class
  proxy (`mutation.py`, shipped) + `history.py`. Real **PIT mutation score** stays **blocked** on the execution
  stage; when it lands it replaces the proxy in the `fault_detection` term (Layer 3). Render + alert tail pending.

| Phase | Layer | Depends on | LLM? | Gate | Status |
|---|---|---|---|---|---|
| T0 trajectory | 2 | — | no | PR-required | **done** |
| T1 scope + coverage + oracle + placeholder | 1 | T0 | no | PR-required | **done** |
| T2 groundedness + oracle judging | 1 | T0 + drivers | yes (provider) | nightly | **done, skips without `[eval]`/creds** |
| T3 gherkin + redundancy + exec-depth | 1→3 | T2 | yes | nightly | **partial (gherkin shipped)** |
| T4 mutation + TPS dashboard | 3 | **execution stage** + T2/T3 | yes | dashboard | **proxy + TPS/history shipped; real mutation blocked** |

Ship T0+T1 first — deterministic, cheap, and alone they catch the define-brief-scoping bug **and** the silent
fallback. T4's real-mutation term is explicitly **blocked** on the missing execution stage — the clean seam
between this report and its sibling.

---

## 13. Constraints & gotchas (from this system's own history)

- **Never run eval inside the agent request path.** Serial blocking Vertex calls in `implement` already starved
  Cloud Run's `/livez` and killed an instance (`ERROR_TIMEOUT`); the runtime `evaluate_plan` scores in a worker
  thread (`asyncio.to_thread`) and only the deterministic metrics; the judged tier runs out of band.
- **A truncated-JSON LLM fallback is silent — always record which path ran.** Quadrupling the coverage matrix
  overran `max_tokens` and the generator silently fell back to the capped heuristic, shipping half the
  behaviours. Every content metric carries a provenance flag (`placeholders.py`); a `detail=True` run that
  produced kind-suffix strings is a failure even if the counts look fine.
- **The define brief is the known-broken surface — lock it hardest.** Treat Scope Precision/Recall + the
  `must_not_scope` hard-negative as a **required** gate, not a nightly nicety.
- **Coverage-matrix downgrade is a brittle substring match.** The metric checks *actual partition presence*, not
  the `"happy only"` metric string.
- **The judge is provider-sourced, and that is enforced.** `ragas_judge.judge` raises on a `None` llm;
  `judged_criteria()` returns `{}` without a provider — a judged run with no creds is a clean skip, not a
  wrong-vendor result.
- **GCS bank state can vanish on redeploy.** The harness uses a temp/isolated bank + recorded fixtures — never
  the prod `GCS_BUCKET`.
- **Mutation needs a runnable SUT.** The truest metric is gated on the not-yet-built execution stage; until
  then oracle-strength + fault-class coverage are the honest proxy, and the report says so.
- **Codegraph grounding gives structure, not execution depth.** The execution-depth rubric (T3) must benchmark
  against a human-executed plan, or it rewards a plausible-but-shallow suite.
- **The working tree, not the commit, is what runs.** Gate on a clean tree so an eval pass can't mask an
  uncommitted edit.
- **Self-learning is a moving target under eval.** The capture/recall hooks mean a later run can differ from an
  earlier one on the *same* pack. Run the golden set with recall **disabled** for the deterministic gate
  (reproducibility), and evaluate the learning effect as its own before/after metric.

---

## 14. Sources

Primary (preferred):
- **ISTQB Certified Tester Foundation Level syllabus** — test-design techniques (equivalence partitioning,
  boundary value analysis, decision tables), requirements coverage, traceability.
- **ISO/IEC/IEEE 29119** (software testing — test techniques, coverage items, traceability) and **IEEE 829**
  (test documentation).
- **Y. Jia & M. Harman, "An Analysis and Survey of the Development of Mutation Testing,"** IEEE TSE 37(5), 2011.
- **PIT / pitest** (`pitest.org`) — mutation testing for the JVM (the luz stack is Java).
- **Google ADK — evaluation docs** and **`adk-python` `eval_metrics.py`** (cross-checked in the KGA report).
- **RAGAS — generation metrics** (`docs.ragas.io`) — Faithfulness, Response Relevancy.
- **Cucumber / Gherkin reference** (`cucumber.io/docs/gherkin`) — declarative-vs-imperative, anti-patterns.
- The three-layer framework, golden-schema, weighted-rubric and calibration protocol: the local
  [`agentic-qa-eval-framework.html`](./agentic-qa-eval-framework.html) evaluation spec.

Secondary / corroborating (treated as *unverified* where they exceed the primary standards):
- LLM-test-generation empirical studies — directional evidence that validity gates precede coverage which
  precedes fault detection; specific percentages vary by study and are not relied on here.
- BDD "scenario smell" practitioner literature — the Gherkin quality checklist in §4.5.

*Cross-check status: ADK + RAGAS metric names carried over from the sibling report's verified source list. The
testing-science measures (coverage adequacy, mutation, traceability) are standard and well-attested in ISTQB /
IEEE 29119 / Jia-Harman. Claims specific to LLM-test-gen numbers and BDD-smell taxonomies are marked unverified
and used only as directional support, not as thresholds.*

---

## Appendix A — Implementation plan (phase by phase) — **as built**

> **Status: BUILT (Layers 1–2) — deterministic T0/T1 + composite + judged tier; real mutation (Layer 3) gated.**
> The TPD-scoring metrics live in the ADK-native eval agent the KGA report produced —
> [`src/test_evaluation/`](../src/test_evaluation/) — as a second engine (`plan_engine.py`), not a parallel
> `tests/eval/metrics/` tree. The genuinely new code was the scope-reuse wiring + `coverage`/`oracle`/`mutation`/
> `placeholders`/`gherkin_lint`/`tps` metrics and the two offline drivers; `trajectory`/`pqs`(→`tps`)/`history`/
> `rubrics`/`node_overlap`/`ragas_judge` were **reused**. Deterministic phases (T0–T1) are required PR checks;
> judged phases (T2–T3) run nightly / on `eval:`; the mutation phase (T4) is gated on the execution stage.

### As-built layout (the TPD half of `src/test_evaluation/`)

```
src/test_evaluation/
  models.py                # + PlanEvalCase, CoverageScore, OracleScore, PlaceholderReport, GherkinReport,
                           #   FaultClassScore, TPSComponents/TPSResult, PlanReport  (scope reuses RetrievalScore)
  metrics/
    trajectory.py          # REUSED verbatim (outer flow + inner round order)
    node_overlap.py        # REUSED for scope (retrieval_scores(scoped, in_scope, must_not_scope)) — no scope_overlap.py
    rubrics.py             # REUSED for the brief (cites_only_real_ids / no_invented_urls)
    ragas_judge.py         # REUSED (provider-sourced faithfulness/relevancy) — no groundedness.py
    history.py             # REUSED (append_run / load_history / regressed)
    coverage.py            # NEW — ac_recall + matrix_completeness + traceability
    oracle.py              # NEW — weak/medium/strong classifier + distribution
    placeholders.py        # NEW — placeholder-leak + provenance (heuristic vs llm)
    mutation.py            # NEW — fault-class coverage (proxy); real PIT hook later (Exec/Layer 3)
    gherkin_lint.py        # NEW — BDD smells (tag hygiene + structure)
    tps.py                 # NEW — the weighted composite (mirrors pqs.py's typed result)
  golden_plans/*.json      # plan_rich · plan_bleed · plan_thin  (§9; LUZ-156281 anchor + 8–15 set pending)
  plan_engine.py           # evaluate_plan(bank, ctx, case, *, detail) -> PlanReport
  eval/                    # shared ADK runner: adk_metrics.tps_score/must_not_scope_leak, config.PLAN_METRICS,
                           #  evalset.plan_eval_set(), runner.run_judged_eval

tests/eval/                # out-of-band harness + tests (imports test_plan_definition → test-side)
  harness_tpd.py           # run_define_offline / run_implement_offline + PlanTrace (reuses harness.py for the pack)
  test_eval_tpd_deterministic.py  # T0 + T1 (PR gate)
  test_eval_tpd_metrics.py        # coverage/oracle/placeholder/gherkin/mutation/tps math (PR gate)
  test_plan_engine.py             # the evaluate_plan engine + the ADK router (PR gate)
  test_eval_tpd_judged.py         # T2 + T3 (nightly)
```

### The TPS composite (`metrics/tps.py`) — as built

```python
TPS_WEIGHTS = {"fault_detection": .30, "brief_groundedness": .25,
               "coverage": .20, "oracle_strength": .15, "trajectory": .10}
def tps(components: TPSComponents) -> TPSResult:
    score = sum(w * getattr(components, k) for k, w in TPS_WEIGHTS.items())
    return TPSResult(tps=round(score, 3), components=components)   # ALWAYS carries both
```

`plan_engine.py` fills the components: `fault_detection = fault.coverage`,
`brief_groundedness = (brief_ok + scope.precision) / 2`, `coverage = ac_recall × matrix_completeness`,
`oracle_strength = orc.score`, `trajectory = 1.0` (neutral at runtime). Each phase is independently shippable
and leaves the suite green; the runtime `evaluate_plan` MCP tool + the ADK router are live on the gateway, and
real mutation (Layer 3) remains blocked on the execution stage.
