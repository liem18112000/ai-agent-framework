# The test oracle — what a scenario *asserts*, and why its strength decides everything

> **Structure update (2026-09-15):** the two golden sets are now ONE unified dataset — `golden/<seed>.json` with nested `pack` / `plan` view sub-objects (the loaders `load_golden()` / `load_golden_plans()` / `load_canaries()` / `load_canary_plans()` project each view; `golden_plans/` has been removed, canaries stay under `golden/canary/`). The scorers moved into an **`engine/` package** — `engine/pack.py::evaluate_pack`, `engine/plan.py::evaluate_plan`, and `engine/loaders.py` (shared pack/plan loading), re-exported from `test_evaluation.engine`. Path references below that say `golden_plans/`, `engine.py`, or `plan_engine.py` describe the pre-merge layout.


**Purpose.** In [`RESEARCH-tpd-evaluation-adk-testsuite.md`](./RESEARCH-tpd-evaluation-adk-testsuite.md), one of
the Layer-1 metrics is **Oracle Strength** (`metrics/oracle.py`), and it carries `0.15` of the Test-Plan Score
— and stands in for fault detection until the execution stage exists. That metric only makes sense if you know
what a *test oracle* is. This page is the concept, grounded in how the Test-Plan-Definition agent (TPD) actually
scores it.

> **Diagram (open in Excalidraw, PNG renders inline):**
> - The oracle-strength spectrum + classifier — [`test-oracle.excalidraw`](./test-oracle.excalidraw) · [`.png`](./test-oracle.png)

![The test-oracle concept. A test step is Given/When/Then; its Then is the oracle — the assertion that decides pass/fail. A strength spectrum runs weak (0.0, asserts only a status code — passes even when the feature is broken) → medium (0.5, a named placeholder) → strong (1.0, a concrete resolvable end-state). A classifier maps each step's `expected` string to a tier (enum-shaped token or a pass-criteria match → strong; a weak-word → weak; else medium), and the mean weight becomes oracle_strength, worth 0.15 of the TPS and a deterministic proxy for mutation score.](./test-oracle.png)

---

## 1. What a test oracle is

A **test oracle** is the mechanism that decides whether a test **passed or failed** — the source of the
*expected* result the test compares the actual result against. In a Gherkin scenario it is the **`Then`** step:

```gherkin
Given a credit-only invoice for an individual customer
When the invoice-run charge job executes
Then the tracking row reaches CREDIT_CARD_CHARGED_PENDING   ← this is the oracle
```

Without an oracle a test can *run* but can't *judge* — it's a script, not a test. And a test is only ever as
good as its oracle: **the weakest link in test design is usually not "did we exercise the code?" but "did we
assert the right thing?"**

**A test plan is a set of oracles.** For the TPD, the plan's scenarios/steps *are* the oracles — so grading the
plan means grading what it would assert, not how many scenarios it produced.

---

## 2. Why oracle *strength* is the whole game

Two scenarios can execute the exact same code path and one catches a regression while the other never will —
the difference is the oracle:

| | Oracle | On a real regression (charge silently fails) |
|---|---|---|
| **Weak** | `Then the response status is 2xx` | still 2xx → **test passes** → bug ships |
| **Strong** | `Then the tracking row reaches CREDIT_CARD_CHARGED_PENDING` | state never reached → **test fails** → bug caught |

A suite full of `assert 200` *looks* complete and green and catches almost nothing — the **execution-depth
gap** the TPD hit against a real human-authored plan. So the metric must grade the **strength** of each oracle,
not just its presence. That is exactly what `metrics/oracle.py` does.

---

## 3. How the TPD scores it (`metrics/oracle.py`)

Each step's `expected` string is classified into one of three tiers, deterministically, **without running
anything**:

| Tier | Weight | What it looks like | How it's detected |
|---|---|---|---|
| **strong** | **1.0** | a concrete, resolvable end-state — an enum/state token like `CREDIT_CARD_CHARGED_PENDING`, or a value that matches the plan's own pass-criteria | an enum-shaped token `[A-Z][A-Z0-9_]{3,}` **or** any `pass_criteria` substring appears |
| **weak** | **0.0** | asserts only acceptance / a status code | contains a weak word: `2xx` `3xx` `4xx` `5xx` `status` `accepted` `succeeds` `is returned` `is processed` `is ready` `unchanged` `without error` `is rejected` |
| **medium** | **0.5** | anything in between | neither of the above |

```python
def classify(expected, pass_criteria=()):
    low = expected.lower()
    if _ENUM.search(expected) or any(p and p.lower() in low for p in pass_criteria):
        return "strong"
    if any(w in low for w in _WEAK):
        return "weak"
    return "medium"

def oracle_strength(steps, pass_criteria=()) -> OracleScore:
    graded = [(e, classify(e, pass_criteria)) for s in steps if (e := s.get("expected"))]
    dist  = {k: sum(t == k for _, t in graded) for k in ("strong", "medium", "weak")}
    score = sum(_WEIGHT[t] for _, t in graded) / len(graded) if graded else 0.0
    return OracleScore(round(score, 3), dist, sorted({e for e, t in graded if t == "weak"}))
```

`oracle_strength` returns a typed **`OracleScore(score, distribution, weak)`**: the **mean weight** across all
steps that assert anything (steps with no `expected` are ignored — nothing is being asserted), the
**strong/medium/weak counts**, and the **list of weak assertions to fix**. Feeding the plan's own
`pass_criteria` in means a step that asserts the plan's declared "passed means…" end-state scores **strong**
even if it isn't enum-shaped.

---

## 4. Where it lands — the TPS and the mutation connection

- **In the score:** `oracle_strength` is `0.15` of the Test-Plan Score
  (`TPS = 0.30·fault_detection + 0.25·brief_groundedness + 0.20·coverage + 0.15·oracle_strength + 0.10·trajectory`).
- **As a proxy for fault detection:** the truest measure of a suite is its **mutation score** — inject faults
  into the system and count how many the suite kills. That needs the tests to *run* (the not-yet-built
  execution stage / Pillar 2 of [`RESEARCH-test-executor-agent.md`](./RESEARCH-test-executor-agent.md)). Until
  then, **oracle strength is the deterministic stand-in**: a strong oracle kills many mutants, a weak one kills
  almost none, so oracle strength is a strong *predictor* of mutation score — and it's measurable now, without
  running anything. When real mutation lands it replaces the proxy in the `fault_detection` term and oracle
  strength stays as its own signal.

---

## 5. A note on oracle types (testing science)

The classic taxonomy — the TPD's oracles are the **specified / end-state** kind:

- **Specified oracle** — expected output comes from the spec/AC ("passed means the invoice status is X"). *What
  the TPD's `pass_criteria`-matched strong oracles are.*
- **Derived / consistency oracle** — expected output derived from another run or an invariant (e.g. "the total
  is unchanged after a read-only call").
- **Metamorphic oracle** — no known exact answer, but a *relation* between inputs/outputs must hold.
- **Human oracle** — a person judges. Expensive; the thing an agentic plan is trying to reduce reliance on.

The TPD deliberately rewards **specified end-state** oracles because they are the ones a downstream automated
executor can check and the ones that actually discriminate — which is why `assert 200` scores `0.0` and a named
end-state scores `1.0`.

---

## Sources

- **ISTQB Foundation syllabus** & **ISO/IEC/IEEE 29119** — test oracle, expected results, test-design techniques.
- E. T. Barr et al., "The Oracle Problem in Software Testing: A Survey," *IEEE TSE* 2015 — the oracle taxonomy.
- Implementation: `src/test_evaluation/metrics/oracle.py`, `plan_engine.py` (the `0.15·oracle_strength` TPS term),
  and [`RESEARCH-tpd-evaluation-adk-testsuite.md`](./RESEARCH-tpd-evaluation-adk-testsuite.md) §4.3.
