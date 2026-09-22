# Test-Plan Definition Agent — Interrogative Implement & Coverage Completeness

**Purpose.** An improvement report for the **Test-Plan Definition (TPD) agent** targeting two concrete
weaknesses observed in `src/test_plan_definition`:

1. **Too few test cases** — `implement` emits a thin set (a flat cap of grounded notes × up to four
   kinds), nowhere near covering "100% of the logic."
2. **One-shot generation** — test **data**, test **cases**, and test **steps** are produced in a single
   pass. That is not where an agent does its best work: it should **interrogate** — ask the user the
   QA/QC judgement calls about each — the way the `define` stage already interrogates methodology / scope
   / metrics.

This report diagnoses both against the current code, then proposes a design that **reuses the machinery
the agent already has** (the interrogation round engine) rather than adding a parallel one.

> **Companion reports.**
> - Output scoring (generate → judge → reflect) — [`RESEARCH-tpd-assured-generation.md`](./RESEARCH-tpd-assured-generation.md).
> - How to measure the improvement (AC-coverage recall, coverage-matrix completeness, oracle strength) — [`RESEARCH-tpd-evaluation-adk-testsuite.md`](./RESEARCH-tpd-evaluation-adk-testsuite.md).
> - Downstream execution (runs the `.feature`, back-fills real coverage/mutation) — [`RESEARCH-test-executor-agent.md`](./RESEARCH-test-executor-agent.md).

---

## 0. TL;DR — deepen the *input*, don't just score the *output*

> **Implementation status (2026-09-10): Q1–Q5 BUILT, agent-based** (commits `63a2d78` Q1–Q4, `fe71da2`
> Q5; 396 pass, ruff clean). The 4th `test-design` define round, the open/uncapped kind taxonomy, the
> interrogative implement (nested `ImplementOrchestrator` → interrogate `case-design`/`data-design`/
> `step-oracle` → generate), and the codegraph coverage matrix (`get-coverage`) are all live. **Q6**
> (executor-certified real coverage/mutation) is the only phase deferred — it needs the
> [Test Executor agent](./RESEARCH-test-executor-agent.md). See §4 for the per-phase detail.

The [assured-generation report](./RESEARCH-tpd-assured-generation.md) improves the **output** of
`implement_plan` (judge → gate → reflect). This report improves its **input**: *what* to generate and *how
much*. The two are orthogonal and compound — a judge can only reward coverage that was designed in the
first place.

| Gap today | Root cause in code | Fix (this report) |
|-----------|--------------------|-------------------|
| **Test set is too small** | `implement/scenarios.py`: `_MAX_NOTES = 8` grounded notes × a **closed** `_FULL_COVERAGE = (happy, negative, boundary, error)`. Two ceilings: the kind set is hard-coded and finite, and the count is capped (one per note×kind, first 8 notes). No test-design technique. | A **coverage engine** with **no caps**: an **open, elicited kind taxonomy** (ask the user for more kinds) and an **unbounded** case count per kind, driven only by covering **100%** of every AC / codegraph branch, with a **traceability + gap report**. |
| **One-shot, non-interrogative** | `implement/generate.py::implement_plan` runs `generate_test_data → generate_scenarios → generate_all_steps` straight through — no questions, no user turns. And the define loop's `ROUNDS` has no **test-design** round, so the method is never chosen/recommended. | A **4th define round `test-design`** (agent-suggested, §3.4) + an **`ImplementSession`** mirroring the resumable `PlanSession` with rounds for **test-case design**, **test-data design**, **test-step / oracle design** — reusing the exact round engine. |

> **Two no-limit principles (this revision).**
> 1. **Kinds are open, not a fixed four.** `(happy, negative, boundary, error)` are only *defaults*. The
>    `case-design` round **explicitly asks the user whether more kinds apply** — security, performance/load,
>    concurrency/idempotency, compliance/audit, accessibility, i18n/l10n, migration/backfill, observability,
>    resilience/chaos, contract/schema, … — and the taxonomy grows with the answer. Never silently cap the
>    kind set.
> 2. **Cases per kind are unbounded.** There is **no numeric cap** on how many cases a kind gets; the
>    enumerator emits as many as the technique yields (every equivalence class, every boundary, every
>    decision rule, every state transition, every dependency failure) until the coverage gap for that
>    kind/behaviour is **empty**. The stopping rule is *100% of the applicable logic covered*, not a count.

> **Note.** `implement` already sits behind a human **approve_plan** gate and a client-owned Yes/No gate;
> this report makes the *content* of that gate a real QA conversation instead of a fait accompli.

---

## 1. Diagnosis (grounded in the current code)

### 1.1 `define` is already interrogative — `implement` is not

`define` is a resumable, multi-turn reconfirm state machine (`define/loop.py::PlanSession`): for each round
in `ROUNDS = ("methodology", "scope", "metrics")` it calls `generate_round(...)`, surfaces the **open**
questions, ingests the user's answers (`common/interrogate/answers.ingest`), distils each into a
`PlanDecision`, and **self-answers** the settled ones. It persists state per round and rehydrates on
resume (`PlanSession.rehydrate`). This is exactly the interaction the user wants — but it stops at the
plan, and its three rounds have **no `test-design` round**: the suite's test-design *method* is never
chosen or recommended; it is implied later by the one-shot generator. (§3.4 adds it as the 4th round.)

`implement` (`implement/generate.py::implement_plan`) does the opposite: it loads the confirmed plan and
runs three generators back-to-back with **zero** user interaction:

```
test_data  = await generate_test_data(plan, plan_pack, …)      # heuristic, or 1 LLM call under `detail`
scenarios  = await generate_scenarios(plan, plan_pack, …)      # the single I3 LLM call
steps      = await generate_all_steps(scenarios, plan, …)      # template/heuristic, or 1 LLM call under `detail`
```

There is no `coverage` / `test-data` / `test-step` interrogation round, no `ImplementSession`, no
questions written for these artifacts. The richest QA decisions — *which cases, which data partitions,
which oracle* — are made silently by one prompt.

### 1.2 The interrogation engine is generic and already has a QA round

The round engine is not define-specific. `common/interrogate/round/base.py` defines a `RoundQuestions`
strategy with a self-registering `registry`; `common/interrogate/questions.py::generate_round` ranks +
caps whatever round you ask for; `answers.ingest` + the `decision_from_answer` distiller close the loop.
Round modules already exist for `business`, `technical`, `qa`, `scope`, `methodology`, `metrics`.

Crucially, **`round/qa.py` already asks the right questions** — coverage bar (happy vs +negative/boundary/
error) and test-data/externals (stub vs real, fixtures) — but it is wired into **KGA refine**, not TPD
implement. The capability exists; it is pointed at the wrong stage. Extending interrogation to implement
is *reuse*, not new infrastructure.

### 1.3 Coverage is a flat cap, not a technique

`implement/scenarios.py::heuristic_scenarios` builds `targets = grounded[:_MAX_NOTES]` (`_MAX_NOTES = 8`)
and emits, per target, the kinds from `_coverage_kinds(plan)` — the full 4 `(happy, negative, boundary,
error)` unless the metrics say "happy only." `test-data` is likewise `grounded[:_MAX_MOCKS]`
(`_MAX_MOCKS = 8`). Consequences:

- **A hard ceiling of ~8 behaviours.** A feature with 30 acceptance criteria silently loses 22 of them.
- **A closed kind set.** `_FULL_COVERAGE` is a fixed 4-tuple `(happy, negative, boundary, error)`. Whole
  categories a real QA needs — security, performance, concurrency/idempotency, compliance, accessibility,
  i18n, migration — cannot appear because there is no way to add a kind; the user is never asked.
- **One scenario per (note, kind).** A single case per pair, so even the four kinds are one-deep. No
  equivalence classes, no boundary values enumerated, no decision tables, no state transitions, no
  per-dependency error paths — the techniques that actually enumerate logic.
- **No traceability or gap signal.** Nothing says "branch X / AC Y is uncovered," so "aim for 100%" has
  no target to close against.

### 1.4 Known gotchas the redesign must not re-hit

- **Silent heuristic fallback.** When the scenario LLM output overran `max_tokens`, generation fell back
  to the heuristic capped at a few notes — quietly. (History: raised `max_tokens` 2000→6000, `_MAX_NOTES`
  3→8.) More cases ⇒ **chunk** generation and detect truncation loudly, never silently cap.
- **Free-text answers not persisted to structure.** `define_plan(answer=…)` corrections did not update the
  structured In-scope/Passed-means fields. The implement rounds must distil answers into **structured
  scenario/data/step specs**, not just prose.
- **Serial Vertex calls → Cloud Run timeout.** Three serial blocking calls once blew the liveness/request
  timeout. Interrogation is *naturally* one bounded turn per round — it fits the proven "1 call per turn"
  shape, unlike a monolithic mega-prompt.

---

## 2. Concepts & terms (test-design techniques)

The vocabulary the coverage engine and the interrogation rounds are built on.

| Term | Definition | Use here |
|------|-----------|----------|
| **Equivalence Partitioning (EP)** | Split each input domain into classes that should behave identically; test one representative per class (valid + each invalid class). | The base enumerator: 1 case per class, not 1 per note. |
| **Boundary Value Analysis (BVA)** | Test the edges of each partition (min, min−1, max, max+1, empty, one, off-by-one). Most defects cluster at boundaries. | Turns "boundary" from one vague case into the actual edge set. |
| **Decision table / cause-effect** | Enumerate combinations of conditions → expected actions; one column per rule. | Combinational business logic (eligibility, pricing, auth matrices). |
| **State-transition testing** | Model states + events; cover states, valid transitions, and *invalid* transitions. | Stateful flows (dunning stages, order lifecycle, retries). |
| **Error / exception-path testing** | One case per failure mode of each dependency (timeout, 5xx, malformed, partial write). | The "error" kind, made systematic per dependency. |
| **Pairwise / combinatorial (t-way)** | Cover all pairs (or t-tuples) of parameter values instead of the full cross-product — bounds the explosion while catching most interaction bugs. | Multi-parameter inputs, feature flags, role×resource. |
| **Risk-based testing (RBT)** | Depth follows risk: money/auth/data-loss/compliance get EP+BVA+decision+error; low-risk gets happy+smoke. | Sets *how deep* each behaviour goes — the interrogation's core judgement. |
| **Test oracle** | The mechanism that decides pass/fail: response status vs **end-state** vs side-effect vs invariant. | The "test-step" round's central question. |
| **Coverage criteria** | Statement / branch / condition / MC-DC / path — increasing strength of "logic covered." | The target the traceability report measures against (branch as the practical aim). |
| **Traceability (RTM)** | A matrix mapping each requirement/branch → the test(s) that cover it; blanks = gaps. | The artifact that makes "100%" measurable and closeable. |

---

## 3. Target design

Two independent, composable changes. Both reuse existing machinery.

### 3.1 Interrogative implement — an `ImplementSession` mirroring `PlanSession`

Add a second interrogation session for the implement stage. It is a near-clone of `define/loop.py::
PlanSession` (resumable, self-answering, decision-distilling) with three new rounds instead of the plan's
three:

| Round | The judgement it surfaces (open) vs self-answers (settled) | Distils into |
|-------|-----------------------------------------------------------|--------------|
| **`case-design`** | (a) **Which kinds apply** — start from the defaults `(happy, negative, boundary, error)` and **ask the user to add any others** (security, performance, concurrency, compliance, accessibility, i18n, migration, resilience, contract, …); the kind set is open. (b) Per behaviour/AC: which **techniques** apply (EP? BVA? decision table? state-transition?). Depth is set by *completeness*, not a cap: enumerate every class/rule/edge/transition/failure. | structured `TestScenario` specs — **as many per kind as needed for 100%**, one per class/rule/edge |
| **`data-design`** | Valid + invalid **partitions** and **boundary values** per field; fixtures; stub-vs-real per dependency; PII/anonymisation; teardown/lifecycle. | `TestData` specs with concrete partitions |
| **`step-oracle`** | The **oracle** per case (status vs end-state vs side-effect vs invariant); precondition/teardown; negative assertions ("no side effects on reject"); idempotency/concurrency checks. | `TestStep` specs (Given/When/Then + explicit assert) |

Reuse verbatim:
- `common/interrogate/round/base.py` — add `CaseDesignRound`, `DataDesignRound`, `StepOracleRound`
  subclasses (self-register by `round`). The existing `qa.py` round is the seed for `case-design`.
- `common/interrogate/questions.py::generate_round`, `answers.ingest`, the `generate_round → open? →
  submit → decision` loop, and the resumable state (`write_plan_state`/`rehydrate` → an analogous
  `write_implement_state`).
- The **LLM-or-heuristic generator switch** (`define/questions.py::make_generator`) so each round
  self-answers the settled calls and only surfaces genuine judgement — exactly as define does.

Flow (client-owned Yes/No each round, like define):

```
approve_plan ─▶ implement (interrogative)
   round case-design  → open Qs → user answers → scenario specs      (1 turn, ≤1 LLM call)
   round data-design  → open Qs → user answers → data specs          (1 turn, ≤1 LLM call)
   round step-oracle  → open Qs → user answers → step/oracle specs   (1 turn, ≤1 LLM call)
   ─▶ generate artifacts from the CONFIRMED specs ─▶ .feature ─▶ [assured loop] ─▶ human gate
```

This keeps **one LLM call per turn** (each round is its own turn), is **resumable** (state persisted per
round under `context_id`), and makes every QA decision an explicit, provenance-carrying `Decision` — fixing
the "free-text answer not persisted to structure" gotcha by construction.

### 3.2 Coverage-completeness engine — from "8 × 4" to a traceable matrix

Replace the flat cap with a **coverage matrix** built from two sources the pipeline already has: the
approved **pack** (acceptance criteria / notes / insights) and the **graphify codegraph** (functions,
branches, dependencies).

1. **Enumerate units of logic.** For each in-scope behaviour: its ACs, its codegraph **branches** (the
   `if`/`switch`/guard nodes), and its dependency edges (the error-path sources). This is the denominator
   for "100%."
2. **Apply the chosen methods per unit** — the techniques the agent recommended and the user confirmed in
   the **`test-design` define round** (§3.4), refined in the implement `case-design` round: EP+BVA for input
   domains, a decision table for combinational guards, a state-transition set for stateful flows, one error
   case per dependency failure mode, pairwise for multi-parameter inputs, plus any **user-added kind**
   (security, performance, …).
3. **Emit a scenario per class/rule/edge** — **as many as the methods yield, uncapped** — each citing the
   AC id **and** the codegraph branch id it covers (traceability).
4. **Produce a coverage-gap report**: branches/ACs/kinds with no scenario. This is the artifact that makes
   "aim for 100%" actionable — the interrogation loops until the gap set is empty or the user accepts the
   residual with a reason.

Design constraints that avoid §1.4's gotchas:
- **No caps — on kinds or on cases.** Delete `_MAX_NOTES`/`_MAX_MOCKS` and the closed `_FULL_COVERAGE`
  tuple. Kinds come from the open, elicited taxonomy; the case count per kind follows the matrix to 100%.
  Risk still sets *which kinds/methods apply* to a behaviour, but never *caps the count* within a chosen one.
- **Chunk generation** (per behaviour or per N scenarios) so a large matrix never overruns `max_tokens`;
  detect truncation and **log loudly**, never silently fall back. The bound is the coverage goal, not tokens.
- **Two-tier certification.** The matrix gives *designed* coverage (structural, cheap). *Executed* coverage
  and **mutation score** (the real "did the tests catch anything" number) come once the
  [Test Executor agent](./RESEARCH-test-executor-agent.md) can run the suite — this report designs the
  input; that one certifies it.

### 3.3 How it composes

```
define (methodology/scope/metrics/TEST-DESIGN)  ← interrogate the PLAN + pick the test-design method(s)  [+4th round, §3.4]
   ▼
implement (case-design/data-design/step-oracle) ← interrogate the ARTIFACTS, apply the chosen methods    [§3.1]
   ▼   coverage matrix + traceability/gap report (aim: every branch/AC/kind covered, uncapped)
generate → JUDGE → gate → reflect          ← score the OUTPUT   [RESEARCH-tpd-assured-generation.md]
   ▼
run → measure real coverage + mutation     ← certify by execution [RESEARCH-test-executor-agent.md]
```

The **`test-design` round picks the method** at plan level (round 4 of define, agent-suggested); the
implement `case-design` round **applies** that method to enumerate concrete cases. Interrogation deepens
*what* gets generated; the assured loop scores *how good* it was; the executor certifies by *running* it.
Each stage is independently shippable and human-gated.

### 3.4 The 4th define round — `test-design` (agent-suggested method selection)

**Requirement.** Add a fourth round to the define loop's first interrogation — today
`ROUNDS = ("methodology", "scope", "metrics")` in `common/testplan/models/plan.py` — so it becomes
`("methodology", "scope", "metrics", "test-design")` (add `ROUND_PREFIX["test-design"] = "tds"`). The round
asks **which test-design method(s)** the suite should use, and the agent **suggests** the answer rather than
leaving it blank.

**Why in `define`, not only `implement`.** The method is a *plan-level* decision (it shapes scope, effort
and the coverage target the user reconfirms), and it must be visible in the plan brief the human approves.
The per-case *application* of the method stays in the implement `case-design` round (§3.1). Round 4 chooses
the tool; the implement round swings it.

**The suggestion engine — grounded in what the agent already has.** A new `TestDesignRound(RoundQuestions)`
(`round = "test-design"`) self-registers in the same registry and self-answers a **recommendation** the user
can accept, override, or extend, drawing on two sources:

- **The KGA pack** (`common/interrogate/pack.py` — notes, insights, the scoped codegraph): the feature's
  real shape. Signals → recommended method:

  | Signal in the pack / codegraph | Recommended test-design method |
  |--------------------------------|--------------------------------|
  | Input fields with ranges / formats / sizes | **Equivalence Partitioning + Boundary Value Analysis** |
  | Combinational business rules (eligibility, pricing, auth matrix) — multiple conditions → one action | **Decision table / cause-effect** |
  | A lifecycle / status machine (dunning stages, order states, retries) | **State-transition testing** |
  | Many independent parameters / feature flags / role×resource | **Pairwise (t-way) combinatorial** |
  | Several external dependencies / integration edges | **Error-path / fault-injection per dependency** |
  | Money / auth / data-loss / compliance risk markers | **Risk-based depth** (stack EP+BVA+decision+error) |
  | An OpenAPI / schema surface | **Schema/contract + property-based** (defer real fuzz to the executor) |

- **Previously collected data** (the round is gated *after* rounds 1–3, so it reads them): the confirmed
  **methodology** (API vs E2E vs UI narrows viable methods), **scope** (which behaviours are in), and
  **metrics** (the pass bar / risk profile), plus recalled **lessons** from the two-tier memory
  (`search_lessons` / `search_memory`) — "for dunning tickets we used state-transition + decision-table
  last time." This is why the round belongs after the others: it is a *synthesis* of everything decided.

**Interaction shape (identical to the other rounds).** The round emits an **open** question — "Recommended
test-design method(s): *state-transition + decision-table* (because the pack shows a dunning state machine
with an eligibility matrix). Accept, change, or **add more**?" — with the recommendation pre-filled and 2–4
options, and it **asks the user to add kinds/methods** the pack could not infer. The answer distils into a
`PlanDecision` and lands in the plan brief; when the pack already settles it, the round *self-answers* and
surfaces nothing (no busywork), consistent with §1.2's "surface only genuine judgement" rule.

> **Research note — how method selection is done in practice.** Test-design-technique *selection* is a
> recognised QA discipline (ISTQB): map product characteristics → technique (input-domain heavy → EP/BVA;
> combinational → decision tables; sequential/stateful → state-transition; high-interaction → combinatorial;
> risk → risk-based depth). Auto-recommending it from an artifact is what tools like RESTGPT (spec →
> enriched rules/examples) and the TestGen/ACH lineage do for *code*; here the agent does it from the **KGA
> pack + codegraph + prior decisions + recalled lessons** — exactly the inputs it already holds. The
> recommendation is a *lead*, never the final word: the human round confirms it.

---

## 4. Roadmap (phased)

**Status: Q1–Q5 BUILT** (commits `63a2d78` = Q1–Q4, `fe71da2` = Q5; 396 pass, ruff clean). Q6 deferred.

| Phase | What | New infra | Payoff |
|-------|------|-----------|--------|
| **Q1 — `test-design` define round** ✅ BUILT | Added the **4th define round** (`ROUNDS += "test-design"`, prefix `tds`): a `TestDesignRound` that **suggests** the method(s) from the pack's shape (signal→method) + rounds 1–3 + the LLM focus, and asks the user to accept / change / add. Lands on `TestPlan.test_design` + the plan brief. | reuse round engine | Method chosen *up front*, agent-recommended, human-confirmed. |
| **Q2 — open kind taxonomy + no caps** ✅ BUILT | Deleted the closed `_FULL_COVERAGE` tuple and `_MAX_NOTES`/`_MAX_MOCKS`; kinds come from `TestPlan.test_kinds` (open, **elicited** — ask for more), case count per kind uncapped; every grounded note enumerated. | none | Many more, traceable cases across *any* kind; a real "gap" signal. |
| **Q3 — `case-design` round** ✅ BUILT | `ImplementSession` (mirrors the define `PlanSession`) + `CaseDesignRound`: the answer updates the plan's open `test_kinds`; decisions distilled + persisted. | reuse round engine | Cases enumerated *with* the user, uncapped. |
| **Q4 — `data-design` + `step-oracle` rounds** ✅ BUILT | `DataDesignRound` (partition/BVA/stub-vs-real) + `StepOracleRound` (end-state vs status oracle) round the interrogation out; distilled to provenance decisions + an implement brief. Nested under an **`ImplementOrchestrator`** (`sub_agents=[interrogate, generate]`). | reuse | Realistic data + end-state oracles decided up front, not `assert 200`. |
| **Q5 — codegraph-driven denominator** ✅ BUILT | `common/testplan/coverage.py`: denominator = requirement units (notes+insights) + **code units = codegraph endpoints + god-node hubs** (graphify is symbol-level → no branch nodes; these are the branch proxy). Requirement×kind traceability + gap report + coverage %; `get-coverage` / `get_coverage`. | codegraph read (exists) | Measurable, closeable coverage target. |
| **Q6 — certify (blocked on executor)** ⏸ | Real executed coverage + mutation score replace the designed-coverage proxy; scenarios cite real branch ids. | [Test Executor agent](./RESEARCH-test-executor-agent.md) | A quality number, not just a design. |

Q1–Q5 needed **no new services** — they reuse the interrogation engine, the pack, and the codegraph. Q6 is
deferred to the executor.

> **Honest scope of "BUILT".** Q3/Q4 distil each answer into a provenance-carrying decision and the
> case-design answer updates the plan's open `test_kinds` (which drives generation); the finer per-field
> *structured* scenario/data/step specs remain a follow-up. Q5's code units are the codegraph's
> **endpoints + hubs**, not literal branches, and "reached" is a **design-time name-match** signal — real
> executed/branch coverage + mutation are Q6 (the executor). The matrix is honest about both.

---

## 5. Constraints to respect (from this system's history)

- **One LLM call per turn.** Interrogation is one bounded round per turn — it *fits* the proven shape, and
  is safer than a single mega-prompt. Do not collapse the rounds into one blocking call.
- **Persist + resume.** Each implement round checkpoints state to GCS keyed by `context_id` (mirror
  `write_plan_state`/`rehydrate`) so a Cloud Run kill resumes, not restarts.
- **Human owns the gate.** The client asks Yes/No each round (as it does for define); the agent only
  self-answers the *settled* calls and surfaces the genuine judgement.
- **Distil answers into structure.** Every answer becomes a provenance-carrying `Decision` → a structured
  scenario/data/step spec (fixes the "free-text not persisted" bug).
- **No caps; ask for more.** There is no fixed kind set and no per-kind count limit. Kinds are seeded from
  defaults but **elicited** — the agent asks the user to add any missing category — and cases per kind are
  bounded only by the 100%-coverage aim. Never silently cap or fall back: chunk generation, detect
  truncation, log loudly. A short suite must be a *reported, user-confirmed* choice, not an invisible ceiling.
- **Reuse, don't fork.** Build on `common/interrogate/round/*` and `PlanSession`; do not spawn a parallel
  interrogation stack.

---

## 6. Net picture & honest gaps

TPD used to interrogate the **plan** (3 rounds) then generate the **artifacts** blind and thin. As BUILT,
it now (a) runs a **4th `test-design` define round** where the agent **suggests** the method from the pack's
shape + prior decisions, (b) interrogates the **artifacts** too — *which kinds, which cases, which data,
which oracle* — via the interrogation engine it already owns, and (c) has replaced the closed `8 × 4` cap
with an **open, elicited kind taxonomy** and an **uncapped**, codegraph-and-AC-driven **coverage matrix**
with a real "aim for 100%" target and a gap report to close against.

**Honest gaps (what's still design-time, by construction).**
- **"100% of logic" is a design-time target until execution exists.** Q1–Q5 maximise *designed* AC/kind/
  code-unit coverage; only the [Test Executor agent](./RESEARCH-test-executor-agent.md) (Q6) can measure
  *executed* coverage and mutation — the true catch-rate. This report deliberately stops at the design boundary.
- **Code units are endpoints/hubs, not branches, and "reached" is a name-match.** Graphify is symbol-level,
  so the coverage denominator uses the codegraph's **endpoints + god-node hubs** as the branch proxy, and a
  unit counts as reached when a scenario/covered-note *names* it — a structural signal, not proof of
  execution. Q6 replaces both with real branch ids + executed coverage.
- **Uncapped cases cost more turns and tokens.** The count is bounded by the coverage goal, not a constant —
  which is the point. Risk decides *which kinds/methods apply* per behaviour; within a chosen kind the
  enumeration runs to completeness and the interrogation lets the user confirm the residual.
- **Codegraph enumeration depends on graph quality.** Where the codegraph is thin (missing repo / gap), the
  matrix degrades to requirement-only and **says so** — it never implies false completeness.
- **Structured specs are a follow-up.** Q3/Q4 distil answers into provenance decisions + update the plan's
  `test_kinds`; the finer per-field structured scenario/data/step specs remain to be wired.

### References
Internal: `test_plan_definition/define/loop.py` (the `PlanSession` to mirror), `common/interrogate/round/`
(the round engine + the seed `qa.py`), `test_plan_definition/implement/scenarios.py` (the `_MAX_NOTES`/kind
logic to replace), `RESEARCH-tpd-assured-generation.md`, `RESEARCH-tpd-evaluation-adk-testsuite.md`,
`RESEARCH-test-executor-agent.md`.
Techniques: ISTQB test-design techniques (EP/BVA/decision-table/state-transition); combinatorial/pairwise
testing (NIST ACTS); risk-based testing; MC-DC/branch coverage criteria; requirements traceability matrix.

---
*Improvement report for `src/test_plan_definition` (2026-09-10). Design-only; reuses the existing
interrogation engine and codegraph. Diagrams: extend `agentic-qa-enhancement-roadmap` with the Q-phases if
built.*
