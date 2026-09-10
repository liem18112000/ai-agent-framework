# Test-Plan Definition Agent — Assured Generation & Critic (Pillars 1 & 4)

**Purpose.** How the *agentic + QA/QC* field hardens the **generation** side of the Testing Agent — the
**Test-Plan Definition (TPD) agent** that turns an approved insight pack into scenarios/steps and a
Gherkin `.feature`. It scopes the two enhancement pillars that live *inside* TPD and wrap its
`implement_plan` call: **Pillar 1 — Assured Test Generation** and **Pillar 4 — Critic · Judge ·
Reflexion**. Every claim is anchored to a source URL; concepts are tabulated.

> **Split note (2026-09-10).** This report was split out of the former `RESEARCH-agentic-qa-enhancements.md`.
> Its execution-side half — **Pillars 2 & 3** (real test execution, self-healing, the API oracle stack),
> delivered by a *new* **Test Executor agent** — now lives in
> [`RESEARCH-test-executor-agent.md`](./RESEARCH-test-executor-agent.md). The two are companions: TPD
> **generates and self-critiques**; the Executor **runs and self-heals**.

> **Diagrams (open in Excalidraw, PNGs render inline):**
> - The Assured Test Loop — [`agentic-qa-assured-loop.excalidraw`](./agentic-qa-assured-loop.excalidraw) · [`.png`](./agentic-qa-assured-loop.png)
> - Enhancement roadmap (all phases P0–P5, both agents) — [`agentic-qa-enhancement-roadmap.excalidraw`](./agentic-qa-enhancement-roadmap.excalidraw) · [`.png`](./agentic-qa-enhancement-roadmap.png)

> **Companion reports.**
> - Gather-side (self-exploring KGA) — [`RESEARCH-self-exploring-knowledge-gather.md`](./RESEARCH-self-exploring-knowledge-gather.md).
> - Execution-side (new Test Executor agent) — [`RESEARCH-test-executor-agent.md`](./RESEARCH-test-executor-agent.md).
> - Scoring the TPD output — [`RESEARCH-tpd-evaluation-adk-testsuite.md`](./RESEARCH-tpd-evaluation-adk-testsuite.md).

---

## 0. TL;DR — one blind call → an assured, self-critiqued loop

**Where TPD was.** `implement_plan` made **one** Claude-on-Vertex call (heuristic fallback otherwise)
and exported a Gherkin `.feature` "for the downstream Test execution stage." Generation quality rode on
that single call: **no quality feedback, no verifier/critic, no self-repair, unscored output** — the
exact failure the memory notes already recorded as "silent heuristic fallback capped at a few notes."

**The field's answer (generation side).** *Don't ship a generated artifact you haven't scored.* Generate
a candidate → **judge** it against a rubric → keep it only if it clears a bar → feed the critique back →
regenerate. Two mature pillars provide this, both wrapping `implement_plan`:

| # | Pillar | Closes the gap of… | Plugs into |
|---|--------|--------------------|-----------|
| **1** | **Assured Test Generation** | one blind LLM call, no quality feedback | wraps `implement_plan` |
| **4** | **Critic · Judge · Reflexion** | no verifier, no self-repair, unscored output | wraps `implement_plan`, before the human gate |

> **Status (2026-09-10): Pillars 1 & 4 are BUILT in-code** — see §4. The remaining generation phases
> (real-coverage gating, mutation certification) are **blocked on the execution stage** that the
> [Test Executor agent](./RESEARCH-test-executor-agent.md) provides.

---

## 1. Concepts & terms (glossary)

### 1.1 Generation & quality

| Term | Definition | Why it matters here |
|------|-----------|---------------------|
| **Assured / guaranteed test improvement** | Emit a generated test **only if** it clears hard filters: it *builds*, *passes reliably* (run N×), and *strictly raises coverage*; discard the rest. Origin: Meta **TestGen-LLM**. | The literal fix for "no regression-safety guarantee." Turns hallucinated tests into a filtered, monotonic-improvement stream. |
| **Coverage-guided iteration** | After each run, feed the *specific uncovered lines/branches* + the *last failure* back into the next prompt; loop to a target %. | The converging loop we were missing — replaces one call with a feedback loop. |
| **Flakiness gate (run-5×)** | Run each candidate several times; drop non-deterministic passes before acceptance. | Cheap, high-value gate that keeps flaky generated tests out of the suite. *(Needs the Executor to run them.)* |
| **Mutation score** | Seed synthetic faults ("mutants") into the code; a test is "good" only if it **kills** mutants. The quality metric coverage cannot give. | Guards against "100% coverage / ~4% mutation" — a suite that covers everything and catches nothing. |
| **Characterization test** | A test that asserts *current* behavior, so a future diff that changes behavior breaks it. | Gives "regression baseline" a concrete meaning. |
| **Focal context** | The *minimal* relevant code (method-under-test + its dependencies) selected to fit the token budget, rather than dumping whole files. | Our **codegraph** is the ready-made retriever for this. |
| **Generate–Validate–Repair** | On a compile/run failure, feed the error back to the LLM to *repair* the test instead of discarding it. | Raises yield per (expensive) Vertex call. |

### 1.2 Critic, judge & reasoning (Pillar 4)

| Term | Definition |
|------|-----------|
| **Planner–executor–critic** | Three roles: a *planner* decomposes, an *executor* carries out, a *critic* reviews and returns corrective feedback. Generalizes Anthropic's orchestrator-workers + evaluator-optimizer. |
| **Generator–verifier (actor–critic)** | One component produces a candidate; a separate **verifier** scores/accepts/rejects. Verification is often easier than generation, so a cheap verifier lifts a stronger generator. |
| **Reflexion** | The agent **verbally reflects** on a failure signal, stores the reflection in episodic memory, and retries — reinforcement via language, not weights. |
| **Self-Refine** | A single model iteratively **generates → self-critiques → refines**, no training needed — the minimal critic loop. |
| **Evaluator–optimizer** (Anthropic) | "One LLM generates while another evaluates and gives feedback in a loop." Use when criteria are clear and feedback is *specific* enough to guide the generator. |
| **LLM-as-a-judge** | Use a strong LLM to score another model's output against a rubric. Known biases: **position, verbosity, self-enhancement** — mitigate by randomizing order, capping length, and using a *different* model family as judge. |
| **G-Eval** | LLM-as-judge via chain-of-thought + form-filling to produce calibrated rubric scores with strong human correlation. |
| **Self-consistency / voting** | Sample K reasoning paths and take the majority/plurality (or judge-merge) to cut single-call variance. |
| **Test oracle** | The mechanism that decides whether an output is correct. On the generation side it is an LLM-judge against acceptance criteria (the *execution* oracles live in the Executor doc). |

---

## 2. The repo & framework landscape

Maturity/stars are point-in-time (≈ Sept 2026) and approximate. **Maintenance flags matter** — see §6.

### Pillar 1 — Assured Test Generation

| Name | URL | What it does | License / status |
|------|-----|--------------|------------------|
| **Meta TestGen-LLM** | https://arxiv.org/abs/2402.09171 | Origin of *Assured Offline LLMSE*: keep a generated test only if it builds → passes reliably → raises coverage. Paper only. | research; **not open-sourced** |
| **Qodo Cover / Cover-Agent** | https://github.com/qodo-ai/qodo-cover | First OSS reimplementation of TestGen-LLM. Coverage-driven loop (build prompt → gen → run → parse coverage → keep-if-raises → iterate). CLI + GH Action. | AGPL-3.0; **"no longer maintained" ~2025** |
| **CoverUp** | https://github.com/plasma-umass/coverup | Coverage-**guided** Python gen: feeds per-line/branch uncovered segments into the prompt; beats CodaMosa. | Apache-2.0; active |
| **ChatUniTest** | https://github.com/ZJU-ACES-ISE/ChatUniTest | LLM Java gen with **Generation-Validation-Repair** + adaptive focal context. | active; published |
| **Meta ACH** | https://arxiv.org/abs/2501.12862 · [FB Eng](https://engineering.fb.com/2025/02/05/security/revolutionizing-software-testing-llm-powered-bug-catchers-meta-ach/) | **Mutation-guided**: generate fault-class-specific mutants, then tests that kill them (targets real fault classes, not generic coverage). | research; deployed at Meta |
| **mutmut / PIT / Stryker** | https://github.com/boxed/mutmut · https://pitest.org · https://stryker-mutator.io | Mutation-testing engines (Python / Java / JS) — score suite *quality*. | OSS |
| **EvoSuite / Pynguin / Diffblue** | https://github.com/EvoSuite/evosuite · https://github.com/se2p/pynguin · https://www.diffblue.com/ | Search-based (Java/Python) & RL generators — deterministic *compile+pass* baselines; LLM used to escape plateaus (CodaMosa). | LGPL / MIT / commercial |

### Pillar 4 — Critic · Judge · Reflexion · Orchestration

| Name | URL | Category | License |
|------|-----|----------|---------|
| **LangGraph / CrewAI / AutoGen / MetaGPT** | https://github.com/langchain-ai/langgraph · https://github.com/crewAIInc/crewAI · https://github.com/microsoft/autogen · https://github.com/FoundationAgents/MetaGPT | orchestration (MetaGPT ships an explicit **QA-Engineer** role) | MIT / MIT / MIT / MIT |
| **OpenAI Agents SDK / Magentic-One** | https://github.com/openai/openai-agents-python · https://arxiv.org/abs/2411.04468 | handoffs + guardrails / orchestrator that re-plans on failure | MIT |
| **Reflexion / Self-Refine / ReAct** | https://arxiv.org/abs/2303.11366 · https://arxiv.org/abs/2303.17651 · https://arxiv.org/abs/2210.03629 | reasoning patterns (self-repair, self-critique) | MIT |
| **AgentCoder / CodeT** | https://arxiv.org/abs/2312.13010 · https://arxiv.org/abs/2207.10397 | programmer+tester+executor trio / dual-execution-agreement oracle | research |
| **DeepEval / promptfoo / Ragas / TruLens** | https://github.com/confident-ai/deepeval · https://github.com/promptfoo/promptfoo · https://github.com/explodinggradients/ragas · https://github.com/truera/trulens | LLM-as-judge & eval harnesses (G-Eval, rubric, faithfulness/groundedness) | Apache / MIT |
| **Anthropic — Building Effective Agents** | https://www.anthropic.com/research/building-effective-agents | the workflow vocabulary (evaluator-optimizer, orchestrator-workers, parallelization-voting) | reference |

---

## 3. Target architecture (patterns)

### 3.1 The Assured Test Loop — *replaces the single `implement_plan` call*
→ [`agentic-qa-assured-loop.png`](./agentic-qa-assured-loop.png)

The core loop every mature system converges on (TestGen-LLM, Qodo Cover, CoverUp, ChatUniTest), with a
judge/reflect stage (Pillar 4). Steps ②–③ that require **real execution** are delivered by the
[Test Executor agent](./RESEARCH-test-executor-agent.md); TPD owns ①, ④–⑥ today:

```
Insight Pack + Codegraph
        │
   ① GENERATE ──────────────────────────────────────── (ensemble ×K; Vertex/Claude)
        │  candidate scenarios + data + steps                          ▲
        ▼                                                              │ ⑤ REFLECT
   ② EXECUTE  (Executor agent — Playwright · behave · Schemathesis)   │   (write "why it failed"
        │                                                │             │    → Memory Bank, feed back)
        ▼                                                │             │
   ③ MEASURE  coverage · flakiness×5 · mutation · schema-conformance   │   ← today: JUDGE rubric score
        │            ▲ ORACLES (Executor): schema/status/auth ·        │      stands in for ②–③
        ▼            │          metamorphic · differential · visual-AI │
   ④ GATE  keep IFF: builds ∧ passes×5 ∧ raises coverage ∧ kills mutant │   ← today: score ≥ threshold
        │ kept ─▶ ⑥ JUDGE (LLM-as-judge rubric) ─▶ approved .feature    │
        └ rejected ────────────────────────────────────────────────────┘
                              → + quality report → HUMAN Yes/No gate (unchanged)
```

Adopt Qodo Cover's four decoupled components as named modules: **Prompt Builder** (focal code + spec +
*last failure + uncovered targets*), **AI Caller** (the Vertex call — invoked *many times*, not once),
**Test Runner** (executes in a sandbox — the Executor agent), **Coverage Parser** (did coverage strictly
increase?). Two-tier metric: **coverage** drives the loop (cheap), **mutation score** certifies the
result (slow, at the end). *Until the Executor exists, the loop's "measure" is the LLM-judge rubric
score — honest about not being real coverage/mutation yet.*

### 3.4 Critic · Judge · Reflexion — *score the output, don't assume it*

Insert a **generator → judge → reflect → (ensemble-)regenerate** inner loop *before* the human gate:

- **LLM-as-judge rubric** (G-Eval via DeepEval/promptfoo): score each scenario on AC-coverage, atomicity,
  testability, traceability, dup-rate, negative/edge coverage, and **faithfulness to the approved knowledge
  pack** (no invented requirements). Use a *different* model family as judge to cut self-enhancement bias.
- **Reflexion loop:** if the score < threshold, write a verbal reflection to the Memory Bank under
  `context_id`, then regenerate with reflections in context. Bounded by N.
- **Ensemble + voting:** generate K× (varied temperature), reconcile by judge-arbitrated dedup-merge — kills
  single-call variance (directly counters our known "silent heuristic fallback capped at few notes").
- **Add it as** lightweight **MCP tools / in-code loop** on the existing TPD bridge *or* a new **QA-Critic
  A2A peer** (`score_scenarios`, `critique_plan`) — either way keyed by the same `context_id`.

---

## 4. Enhancement roadmap (TPD phases)
→ [`agentic-qa-enhancement-roadmap.png`](./agentic-qa-enhancement-roadmap.png) (full P0–P5, both agents)

Ordered lowest-effort/highest-certainty → highest-assurance. The execution-dependent phases (P1/P3) are
the [Test Executor agent](./RESEARCH-test-executor-agent.md)'s; the TPD-side phases are:

| Phase | What | Pillars | New infra | Payoff |
|-------|------|---------|-----------|--------|
| **P0 — prompt-only** ✅ BUILT | Guideline-grounded scenario prompt (Gherkin best-practices as context) + failure/uncovered feedback appended each turn; LLM enriches the spec (RESTGPT-style). | 1, 4 | none | Sharper `.feature`, no new services. |
| **P2 — assured loop** ✅ BUILT (in-code; judge-gated) | Wrap `implement_plan` in generate→**judge**→**gate**→reflect→regenerate. Real build ∧ pass×5 ∧ +coverage gating is **blocked on the Executor**. Codegraph = focal context. | 1 | none (judge) / Executor for real coverage | Regression-safety, evidence-based approval. |
| **P4 — critic & self-repair** ✅ BUILT (in-code) | LLM-judge rubric (`JudgeVerdict`, 7 dims); Reflexion loop; ensemble+vote seam on scenario gen. | 4 | +1 A2A peer *or* MCP tools | Scored, self-repaired output. |
| **P5 — mutation certification** ⏸ deferred | Mutation score (mutmut/PIT/Stryker) as final certification; fault-class-targeted negatives from insights (ACH). | 1 | mutation run (needs the Executor to run the suite) | A *quality* number, not just coverage. |

> **Implementation status (2026-09-09/10).** **P0 + the in-code slice of P4 are BUILT** (no new infra;
> offline-verifiable; 384 pass, ruff clean). Concretely:
> - **P0** — `GHERKIN_GUIDELINES` + `PACK_GROUNDING` (RESTGPT-style "mine the pack, invent nothing")
>   injected into `scenarios_prompt`/`steps_prompt`; a `revision_feedback()` slot appends the judge's
>   reflections on each regenerate turn (`common/testplan/llm/prompts.py`).
> - **P4 (in-code)** — the **Assured Generation Loop** `run_assured_scenarios` (`test_plan_definition/
>   implement/assured.py`): generate → **LLM-as-judge rubric** (`JudgeVerdict`, 7 dimensions:
>   ac-coverage/atomicity/testability/traceability/faithfulness/negative-edge/non-dup) → **gate** on
>   `score ≥ threshold` → **reflect** (feed the judge's imperative fixes back) → **regenerate**,
>   bounded by `TPD_ASSURED_MAX_ITERS` (default 2). **Opt-in** behind `TPD_ASSURED` / `implement_plan(
>   assured=True)` so the default path stays the **I3 single LLM call**. Loop state is checkpointed to
>   GCS (`assured.json`, keyed by `context_id`) so a Cloud-Run kill **resumes, not restarts**. The
>   `AssuredReport` score rides on `ImplementResult` and is surfaced to the human before the Yes/No gate.
>
> **Honest gap:** with no execution stage yet, the loop's "measure" is the **judge rubric score**, *not*
> real coverage / flakiness×5 / mutation / schema-conformance. P2's real-coverage gate and P5's mutation
> certification unlock once the [Test Executor agent](./RESEARCH-test-executor-agent.md) can run the `.feature`.

**Constraints to respect (from this system's history):**
- Keep **one LLM call per iteration** — three serial blocking Vertex calls previously blew the Cloud Run
  liveness/request timeout. The Assured Loop is bounded and per-iteration, opt-in, default off.
- **Persist loop state to GCS** keyed by `context_id` — a Cloud Run redeploy has wiped in-flight memory-bank
  state before. The loop must *resume*, not restart.
- **Human owns the final gate** — all auto-loops (assured/reflexion/ensemble) are internal and bounded; the
  Claude client still asks Yes/No before approve / approve_plan, now with judge scores attached.
- **Ground in the codegraph** — focal context and fault targeting read from the graphify codegraph the
  pipeline already builds.

---

## 5. Net picture (TPD scope)

The TPD stage stays **linear and human-gated on the outside**, but its single blind `implement_plan` call
becomes a bounded **generate → judge → gate → reflect → regenerate** inner loop with a **persisted quality
score**. That closes the generation-side gaps — no critic, no quality feedback, unscored output — while
reusing the existing MCP/A2A wiring, the GCS Memory Bank, and the codegraph. The `.feature` we export stops
being an unscored artifact; the remaining step is to make it a *run* artifact — the job of the
[Test Executor agent](./RESEARCH-test-executor-agent.md).

---

## 6. Caveats & source hygiene

- **Maintenance flags:** Qodo Cover is **"no longer maintained" (~2025)** — vendor/fork it, don't depend on
  upstream. **jqwik** is in maintenance mode.
- **Vendor claims** (Diffblue "100% compiling") are self-reported — directionally credible, not independently
  verified here.
- **Not open-sourced:** Meta **TestGen-LLM** and **ACH** are papers; Qodo Cover is the closest OSS proxy.
- **Metrics** treated as solid (cross-checked ≥2 sources): TestGen-LLM funnel (≈75% build / 57% pass
  reliably / 25% raise coverage / 73% engineer-accepted); coverage ≠ quality (100% cov / ~4% mutation).
- **Single model family caveat:** we run only Claude-on-Vertex, so the judge and generator share a family —
  self-enhancement bias is only *partly* mitigated (strict separate rubric prompt, small-token verdict). A
  cross-family judge would be stronger.

### Primary sources (selection)
TestGen-LLM https://arxiv.org/abs/2402.09171 · Qodo Cover https://github.com/qodo-ai/qodo-cover · CoverUp
https://arxiv.org/abs/2403.16218 · ChatUniTest https://arxiv.org/abs/2305.04764 · Meta ACH
https://arxiv.org/abs/2501.12862 · Reflexion https://arxiv.org/abs/2303.11366 · Self-Refine
https://arxiv.org/abs/2303.17651 · LLM-as-judge/MT-Bench https://arxiv.org/abs/2306.05685 · G-Eval
https://arxiv.org/abs/2303.16634 · DeepEval https://github.com/confident-ai/deepeval · promptfoo
https://github.com/promptfoo/promptfoo · MetaGPT https://github.com/FoundationAgents/MetaGPT · Anthropic
Building Effective Agents https://www.anthropic.com/research/building-effective-agents · A2A
https://a2a-protocol.org · MCP https://modelcontextprotocol.io

---
*Split from the former `RESEARCH-agentic-qa-enhancements.md` (2026-09-10). Execution-side pillars (2 & 3)
in [`RESEARCH-test-executor-agent.md`](./RESEARCH-test-executor-agent.md). Diagrams authored in Excalidraw;
regenerate PNGs with the repo's `render_excalidraw.py`.*
