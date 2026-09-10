# Agentic QA / QC & Automation-Testing — Research → Enhancement Report

**Purpose.** A deep scan of the *agentic + QA/QC + automation-testing* field (real open-source repos,
frameworks, and published systems) and a concrete, staged plan for how each finding can **considerably
enhance the current Testing Agent**. Every claim is anchored to a source URL; concepts and terms are
tabulated; the target architecture is drawn in two Excalidraw diagrams beside this file.

> **Diagrams (open in Excalidraw, PNGs render inline):**
> - Enhancement roadmap — [`agentic-qa-enhancement-roadmap.excalidraw`](./agentic-qa-enhancement-roadmap.excalidraw) · [`.png`](./agentic-qa-enhancement-roadmap.png)
> - The Assured Test Loop — [`agentic-qa-assured-loop.excalidraw`](./agentic-qa-assured-loop.excalidraw) · [`.png`](./agentic-qa-assured-loop.png)

> **Companion report (gather-side).** This report is test-plan / execution-side. The first agent — turning
> the Knowledge Gathering Agent into a *self-exploring* researcher that starts from a blank/thin issue and
> reaches internal memory + Atlassian search + external web/LLM — is covered in
> [`RESEARCH-self-exploring-knowledge-gather.md`](./RESEARCH-self-exploring-knowledge-gather.md).

---

## 0. TL;DR — the one gap and the four pillars

**Where we are.** The Testing Agent is two A2A microservices driven by a Claude client over MCP, sharing a
GCS Memory Bank threaded by one `context_id`: `gather_knowledge → refine → approve → define_plan →
approve_plan → implement_plan → get_scenarios`. `implement_plan` makes **one** Claude-on-Vertex call
(heuristic fallback otherwise) and exports a Gherkin `.feature` "for the downstream Test execution stage."

**The gap.** That downstream stage **does not exist yet**. The pipeline generates plausible scenarios, then
stops — with **no execution, no run→fix→rerun loop, no self-healing, no verifier/critic, no test oracle,
and no coverage/quality feedback**. Generation quality rides on a single LLM call.

**The field's answer.** The entire post-2024 agentic-testing field converges on one shape: **don't emit a
test you haven't run.** Generate a candidate → execute it → measure a signal → keep it only if it provably
helps → feed failures back → repeat. Around that core loop sit four enhancement pillars, each a mature body
of OSS work that plugs into a specific stage of our pipeline:

| # | Pillar | Closes the gap of… | Plugs into |
|---|--------|--------------------|-----------|
| **1** | **Assured Test Generation** | one blind LLM call, no quality feedback | wraps `implement_plan` |
| **2** | **Real Test Execution + Self-Healing** | no execution, no heal, no triage | **new stages** after `get_scenarios` |
| **3** | **API Oracle Stack** | heuristic `assert 200`, no real oracle | the execution / assert layer (API-first) |
| **4** | **Critic · Judge · Reflexion** | no verifier, no self-repair, unscored output | wraps `implement_plan`, before the human gate |

---

## 1. Concepts & terms (glossary)

Grouped by pillar. These are the vocabulary you need to read the rest of the report and the diagrams.

### 1.1 Generation & quality

| Term | Definition | Why it matters here |
|------|-----------|---------------------|
| **Assured / guaranteed test improvement** | Emit a generated test **only if** it clears hard filters: it *builds*, *passes reliably* (run N×), and *strictly raises coverage*; discard the rest. Origin: Meta **TestGen-LLM**. | The literal fix for "no regression-safety guarantee." Turns hallucinated tests into a filtered, monotonic-improvement stream. |
| **Coverage-guided iteration** | After each run, feed the *specific uncovered lines/branches* + the *last failure* back into the next prompt; loop to a target %. | The converging loop we're missing — replaces one call with a feedback loop. |
| **Flakiness gate (run-5×)** | Run each candidate several times; drop non-deterministic passes before acceptance. | Cheap, high-value gate that keeps flaky generated tests out of the suite. |
| **Mutation score** | Seed synthetic faults ("mutants") into the code; a test is "good" only if it **kills** mutants. The quality metric coverage cannot give. | Guards against "100% coverage / ~4% mutation" — a suite that covers everything and catches nothing. |
| **Characterization test** | A test that asserts *current* behavior, so a future diff that changes behavior breaks it. | Gives "regression baseline" a concrete meaning. |
| **Focal context** | The *minimal* relevant code (method-under-test + its dependencies) selected to fit the token budget, rather than dumping whole files. | Our **codegraph** is the ready-made retriever for this. |
| **Generate–Validate–Repair** | On a compile/run failure, feed the error back to the LLM to *repair* the test instead of discarding it. | Raises yield per (expensive) Vertex call. |

### 1.2 Execution & self-healing

| Term | Definition |
|------|-----------|
| **Self-healing locator** | When a selector fails to resolve, score candidate elements in the *current* DOM against a stored fingerprint (text/role/position/neighbors) and swap in the best match — continue instead of failing. |
| **Accessibility-tree (a11y) grounding** | Perceive/act via the browser's semantic accessibility tree (roles, names, states), not raw HTML or pixels. Compact (~200–400 tokens), stable, maps to `getByRole`. |
| **DOM / indexed-element grounding** | Traverse the DOM, number interactive elements, give the LLM the list ("click 5"); map the index back to the node. Cheap and precise on dense UIs. |
| **Vision / pixel grounding** | The model looks at a screenshot and outputs coordinates/target. Works on canvas / native / cross-origin UIs; higher cost, weaker on tiny targets. |
| **Computer-use** | An LLM given a generic `computer` tool loop (screenshot → reason → mouse/keyboard → screenshot…), driving a real desktop/browser like a human. |
| **Visual regression / visual-AI oracle** | Decide pass/fail on *appearance/layout* by comparing a rendered screenshot to an approved **baseline** with perceptual AI (ignores sub-perceptual noise). Catches what "DOM node exists" misses. |
| **Flaky test / quarantine** | A test that passes and fails non-deterministically. *Quarantine* isolates a confirmed-flaky test so it still runs but no longer blocks merges, with an audit trail. |
| **Trace / replay** | A rich replayable artifact of a run (steps, DOM snapshots, network, screenshots) for debugging and as input to a healer/triage agent. |
| **Deterministic vs agentic execution** | *Deterministic*: fixed compiled steps — fast, repeatable, brittle. *Agentic*: an LLM decides each action live — adaptive, slow, non-deterministic. Best practice: **agent discovers once → compile to deterministic → agent re-engages only to heal.** |

### 1.3 API / property / spec / contract testing

| Term | Definition |
|------|-----------|
| **Property-based testing (PBT)** | Assert an *invariant* ("for all valid x, P(x) holds"); the framework auto-generates many inputs and searches for a counterexample. Lineage: QuickCheck → Hypothesis / fast-check / jqwik. |
| **Shrinking** | When a generated input fails, automatically reduce it to the *minimal* failing example, so the bug report is small and deterministic. |
| **Stateful / model-based testing** | Generate *sequences* of operations against a state model (create→get→delete), checking invariants after each step — not single isolated calls. |
| **The oracle problem** | The core difficulty that for many inputs there is *no cheap way* to decide whether the output is correct. Metamorphic and differential testing are the two canonical pseudo-oracles. |
| **Metamorphic testing (MT)** | Check a **relation between outputs** of multiple runs on transformed inputs (e.g. "adding a filter only narrows results"; "create-then-read echoes the written fields"). A violated relation = a bug — **no ground truth needed.** |
| **Differential testing** | Run the *same input* through ≥2 implementations/versions (old vs new deploy, two replicas) and diff the responses; any divergence flags a regression. Consensus *is* the oracle. |
| **Consumer-driven contract (CDC)** | The consumer's test records the exact requests/responses it relies on into a **contract** ("pact"); the provider is verified in isolation against it. Pins integration without deploying the whole system. |
| **Stateful fuzzing** | Fuzz *ordered sequences* of requests, feeding earlier response values into later ones to reach deep states. RESTler infers **producer–consumer** dependencies to build them. |
| **Coverage-guided fuzzing** | Instrument the target, measure coverage, and *evolve* inputs that reach new code paths (AFL/libFuzzer lineage; EvoMaster's white-box mode is the API analogue). |

### 1.4 Orchestration, reasoning & oracles

| Term | Definition |
|------|-----------|
| **Planner–executor–critic** | Three roles: a *planner* decomposes, an *executor* carries out, a *critic* reviews and returns corrective feedback. Generalizes Anthropic's orchestrator-workers + evaluator-optimizer. |
| **Generator–verifier (actor–critic)** | One component produces a candidate; a separate **verifier** scores/accepts/rejects. Verification is often easier than generation, so a cheap verifier lifts a stronger generator. |
| **ReAct** | *Reason + Act*: interleave chain-of-thought with tool calls, grounding each next thought in the last observation. |
| **Reflexion** | The agent **verbally reflects** on a failure signal, stores the reflection in episodic memory, and retries — reinforcement via language, not weights. |
| **Self-Refine** | A single model iteratively **generates → self-critiques → refines**, no training needed — the minimal critic loop. |
| **Evaluator–optimizer** (Anthropic) | "One LLM generates while another evaluates and gives feedback in a loop." Use when criteria are clear and feedback is *specific* enough to guide the generator. |
| **LLM-as-a-judge** | Use a strong LLM to score another model's output against a rubric. Known biases: **position, verbosity, self-enhancement** — mitigate by randomizing order, capping length, and using a *different* model family as judge. |
| **G-Eval** | LLM-as-judge via chain-of-thought + form-filling to produce calibrated rubric scores with strong human correlation. |
| **Self-consistency / voting** | Sample K reasoning paths and take the majority/plurality (or judge-merge) to cut single-call variance. |
| **Test oracle** | The mechanism that decides whether an output is correct. In agentic QA it is often generated tests + execution agreement, or an LLM-judge against acceptance criteria. |
| **MCP / A2A** | **MCP** = open JSON-RPC client↔server standard exposing tools/resources/prompts to an LLM host (Claude↔bridge). **A2A** = open agent↔agent protocol: Agent Cards, JSON-RPC/HTTP, SSE, tasks/messages/artifacts. Both already used here — the seam for adding new QA agents/tools. |

---

## 2. The repo & framework landscape

Curated to the most relevant, most maintained projects, grouped by pillar. Maturity/stars are point-in-time
(≈ Sept 2026) and approximate. **Maintenance flags matter** — see §6.

### Pillar 1 — Assured Test Generation

| Name | URL | What it does | License / status |
|------|-----|--------------|------------------|
| **Meta TestGen-LLM** | https://arxiv.org/abs/2402.09171 | Origin of *Assured Offline LLMSE*: keep a generated test only if it builds → passes reliably → raises coverage. Paper only. | research; **not open-sourced** |
| **Qodo Cover / Cover-Agent** | https://github.com/qodo-ai/qodo-cover | First OSS reimplementation of TestGen-LLM. Coverage-driven loop (build prompt → gen → run → parse coverage → keep-if-raises → iterate). CLI + GH Action. | AGPL-3.0; **"no longer maintained" ~2025** |
| **CoverUp** | https://github.com/plasma-umass/coverup | Coverage-**guided** Python gen: feeds per-line/branch uncovered segments into the prompt; beats CodaMosa. | Apache-2.0; active |
| **ChatUniTest** | https://github.com/ZJU-ACES-ISE/ChatUniTest | LLM Java gen with **Generation-Validation-Repair** + adaptive focal context. | active; published |
| **Meta ACH** | https://arxiv.org/abs/2501.12862 · [FB Eng](https://engineering.fb.com/2025/02/05/security/revolutionizing-software-testing-llm-powered-bug-catchers-meta-ach/) | **Mutation-guided**: generate fault-class-specific mutants, then tests that kill them (targets real fault classes, not generic coverage). | research; deployed at Meta |
| **mutmut / PIT / Stryker** | https://github.com/boxed/mutmut · https://pitest.org · https://stryker-mutator.io | Mutation-testing engines (Python / Java / JS) — score suite *quality*. | OSS |
| **SWE-agent / mini-swe-agent** | https://github.com/SWE-agent/SWE-agent · https://github.com/SWE-agent/mini-swe-agent | Reference *agentic run→observe→fix* loop; mini is a ~100-line template. | MIT |
| **Aider** | https://aider.chat/docs/usage/lint-test.html | AI pair-programmer with an auto lint/test loop (runs tests, feeds errors back, auto-fixes). | Apache-2.0 |
| **EvoSuite / Pynguin / Diffblue** | https://github.com/EvoSuite/evosuite · https://github.com/se2p/pynguin · https://www.diffblue.com/ | Search-based (Java/Python) & RL generators — deterministic *compile+pass* baselines; LLM used to escape plateaus (CodaMosa). | LGPL / MIT / commercial |

### Pillar 2 — Real Test Execution + Self-Healing

| Name | URL | Grounding | License / status |
|------|-----|-----------|------------------|
| **Playwright** (runner) | https://playwright.dev/ | DOM/selector (getByRole) | Apache-2.0 |
| **Playwright MCP** | https://github.com/microsoft/playwright-mcp | a11y-tree snapshots w/ `ref`s | Apache-2.0; MS-official |
| **Playwright Test Agents** (Planner/Generator/Healer) | https://playwright.dev/docs/test-agents | a11y + traces | Apache-2.0; `--loop=claude` |
| **browser-use** | https://github.com/browser-use/browser-use | DOM-indexed (+ optional vision) | MIT; dominant OSS browser agent |
| **Skyvern** | https://github.com/Skyvern-AI/skyvern | vision-primary | AGPL-3.0 |
| **Stagehand** | https://github.com/browserbase/stagehand | a11y-tree; self-heal primitives | MIT |
| **Midscene.js / Magnitude** | https://github.com/web-infra-dev/midscene · https://github.com/magnitudedev/magnitude | vision; deterministic replay cache | MIT / Apache-2.0 |
| **Healenium** | https://github.com/healenium/healenium | DOM fingerprint self-heal (Selenium) | Apache-2.0 |
| **Anthropic computer-use demo** | https://github.com/anthropics/anthropic-quickstarts | pixel/vision + coordinates | MIT |
| **Applitools Eyes** | https://applitools.com/platform/eyes/ | perceptual visual-AI oracle | commercial (OSS SDKs) |

### Pillar 3 — API Oracle Stack

| Name | URL | Approach | Input | License / status |
|------|-----|----------|-------|------------------|
| **Schemathesis** | https://github.com/schemathesis/schemathesis | property-based + fuzzing; **spec is generator *and* oracle** | OpenAPI / GraphQL | MIT; active |
| **RESTler** | https://github.com/microsoft/restler-fuzzer | stateful fuzzing + security checkers | OpenAPI | MIT; MS Research |
| **EvoMaster** | https://github.com/WebFuzzing/EvoMaster | search-based white/black-box gen (coverage + fault) | OpenAPI/GraphQL/RPC | LGPL-3.0 |
| **RestTestGen** | https://github.com/SeUniVr/RestTestGen | Operation-Dependency-Graph gen | OpenAPI | Apache-2.0 |
| **Hypothesis / fast-check / jqwik** | https://github.com/HypothesisWorks/hypothesis · https://github.com/dubzzz/fast-check · https://github.com/jqwik-team/jqwik | property-based engines (Py / JS / Java) | code | MPL / MIT / EPL |
| **Pact** | https://docs.pact.io | consumer-driven contracts | consumer test | MIT |
| **Karate / REST Assured / Tavern / Newman** | https://github.com/karatelabs/karate · https://github.com/rest-assured/rest-assured · https://github.com/taverntesting/tavern · https://github.com/postmanlabs/newman | BDD / fluent / declarative / collection runners | Gherkin / code / YAML / JSON | OSS |
| **RESTGPT / APITestGenie** | https://github.com/selab-gatech/RESTGPT · https://arxiv.org/abs/2604.02039 | **LLM enriches the spec** (rules + example values) / drafts tests from requirements+OpenAPI | OpenAPI + LLM | MIT / research |

### Pillar 4 — Critic · Judge · Reflexion · Orchestration

| Name | URL | Category | License |
|------|-----|----------|---------|
| **LangGraph / CrewAI / AutoGen / MetaGPT** | https://github.com/langchain-ai/langgraph · https://github.com/crewAIInc/crewAI · https://github.com/microsoft/autogen · https://github.com/FoundationAgents/MetaGPT | orchestration (MetaGPT ships an explicit **QA-Engineer** role) | MIT / MIT / MIT / MIT |
| **OpenAI Agents SDK / Magentic-One** | https://github.com/openai/openai-agents-python · https://arxiv.org/abs/2411.04468 | handoffs + guardrails / orchestrator that re-plans on failure | MIT |
| **Reflexion / Self-Refine / ReAct** | https://arxiv.org/abs/2303.11366 · https://arxiv.org/abs/2303.17651 · https://arxiv.org/abs/2210.03629 | reasoning patterns (self-repair, self-critique) | MIT |
| **AgentCoder / CodeT** | https://arxiv.org/abs/2312.13010 · https://arxiv.org/abs/2207.10397 | programmer+tester+executor trio / dual-execution-agreement oracle | research |
| **DeepEval / promptfoo / Ragas / TruLens** | https://github.com/confident-ai/deepeval · https://github.com/promptfoo/promptfoo · https://github.com/explodinggradients/ragas · https://github.com/truera/trulens | LLM-as-judge & eval harnesses (G-Eval, rubric, faithfulness/groundedness) | Apache / MIT |
| **OpenHands** | https://github.com/All-Hands-AI/OpenHands | autonomous SWE/QA agent (writes code, runs tests, verifies) | MIT |
| **Anthropic — Building Effective Agents** | https://www.anthropic.com/research/building-effective-agents | the workflow vocabulary (evaluator-optimizer, orchestrator-workers, parallelization-voting) | reference |

---

## 3. Target architecture (patterns)

See the two diagrams beside this file. This section is the written companion.

### 3.1 The Assured Test Loop — *replaces the single `implement_plan` call*
→ [`agentic-qa-assured-loop.png`](./agentic-qa-assured-loop.png)

The core loop every mature system converges on (TestGen-LLM, Qodo Cover, CoverUp, ChatUniTest), extended here
with self-heal (Pillar 2), oracles (Pillar 3) and a judge/reflect stage (Pillar 4):

```
Insight Pack + Codegraph
        │
   ① GENERATE ──────────────────────────────────────── (ensemble ×K; Vertex/Claude)
        │  candidate scenarios + data + steps                          ▲
        ▼                                                              │ ⑤ REFLECT
   ② EXECUTE  ── UI locator break ─▶ Self-Heal ─ re-run ─┐   (write "why it failed"
        │  (Playwright · behave · Schemathesis for API)  │    → Memory Bank, feed back)
        ▼                                                │             │
   ③ MEASURE  coverage · flakiness×5 · mutation · schema-conformance   │
        │            ▲ ORACLES: schema/status/auth · metamorphic ·     │
        ▼            │          differential (API) · visual-AI (UI)    │
   ④ GATE  keep IFF: builds ∧ passes×5 ∧ raises coverage ∧ kills mutant │
        │ kept ─▶ ⑥ JUDGE (LLM-as-judge rubric) ─▶ approved .feature    │
        └ rejected ────────────────────────────────────────────────────┘
                              → + quality report → HUMAN Yes/No gate (unchanged)
```

Adopt Qodo Cover's four decoupled components as named modules: **Prompt Builder** (focal code + spec +
*last failure + uncovered targets*), **AI Caller** (the Vertex call — invoked *many times*, not once),
**Test Runner** (executes in a sandbox), **Coverage Parser** (did coverage strictly increase?). Two-tier
metric: **coverage** drives the loop (cheap), **mutation score** certifies the result (slow, at the end).

### 3.2 Execution + self-healing — *the missing stage*

Winning production pattern: **agent discovers once → compile to deterministic → agent heals only on
failure** (Octomind's "AI doesn't belong in test runtime"). Concretely:

- **Backbone:** Playwright runner + `playwright-bdd`/`behave` executes the existing `.feature` files.
- **Step binding:** Playwright MCP (a11y snapshots, ~300 tokens/step) — Claude-native, deterministic-mappable.
- **Discovery for deferred UI/E2E:** Playwright Test Agents (Planner/Generator/Healer, `--loop=claude`);
  browser-use / Skyvern / Midscene where DOM grounding fails (vision).
- **Self-heal loop:** Healer replays the failing step, inspects current UI, patches the locator/wait/data,
  re-runs until green — **every heal surfaced for human review** (a silent retarget can hide a real
  regression). Route the patch through the same Yes/No gate the pipeline already uses.
- **Triage:** a Claude agent over the Playwright trace classifies each failure → **Actual Bug / UI-change
  (heal) / Flaky (quarantine) / Environment**.

### 3.3 API oracle stack — *real oracles instead of `assert 200`*

The single biggest oracle upgrade needs only the OpenAPI surface we already have:

- **Schemathesis** wraps execution → every scenario gets `response_schema_conformance`,
  `status_code_conformance`, `content_type_conformance`, `not_a_server_error`, `negative_data_rejection`,
  `positive_data_acceptance`, `ignored_auth` **for free**. `assert 200` becomes "conforms to the contract."
- **Property-based data** (Hypothesis via Schemathesis) → thousands of conforming + boundary + malformed
  inputs, each failure **shrunk** to a minimal reproducer droppable into a `.feature` example.
- **Stateful sequences** (RESTler / RestTestGen producer–consumer graph, inferred from codegraph+OpenAPI) →
  realistic multi-step scenarios *and* deep security checkers (use-after-free, resource-leak, user-namespace).
- **Oracle-free checks for invented data** — metamorphic relations (idempotent GET, create-then-read echo,
  filter-only-narrows, pagination-union) and differential mode (old vs new revision).
- **Contracts** (Pact) where the codegraph shows cross-service consumption.

### 3.4 Critic · Judge · Reflexion — *score the output, don't assume it*

Insert a **generator → judge → reflect → (ensemble-)regenerate** inner loop *before* the human gate:

- **LLM-as-judge rubric** (G-Eval via DeepEval/promptfoo): score each scenario on AC-coverage, atomicity,
  testability, traceability, dup-rate, negative/edge coverage, and **faithfulness to the approved knowledge
  pack** (no invented requirements). Use a *different* model family as judge to cut self-enhancement bias.
- **Reflexion loop:** if the score < threshold, write a verbal reflection to the Memory Bank under
  `context_id`, then regenerate with reflections in context. Bounded by N.
- **Ensemble + voting:** generate K× (varied temperature), reconcile by judge-arbitrated dedup-merge — kills
  single-call variance (directly counters our known "silent heuristic fallback capped at few notes").
- **Add it as** a new **QA-Critic A2A peer** (its own Agent Card: `score_scenarios`, `critique_plan`) *or*
  as lightweight **MCP tools** on the existing bridges — either way keyed by the same `context_id`.

---

## 4. Enhancement roadmap (phased)
→ [`agentic-qa-enhancement-roadmap.png`](./agentic-qa-enhancement-roadmap.png)

Ordered lowest-effort/highest-certainty → highest-assurance. Each phase is independently shippable.

| Phase | What | Pillars | New infra | Payoff |
|-------|------|---------|-----------|--------|
| **P0 — prompt-only** ✅ BUILT | Guideline-grounded scenario prompt (Gherkin best-practices as context) + failure/uncovered feedback appended each turn; LLM enriches the OpenAPI spec (RESTGPT-style). | 1, 3, 4 | none | Sharper `.feature`, no new services. |
| **P1 — execution backbone** | Playwright + `playwright-bdd`/`behave` runs the `.feature`; Playwright MCP binds steps. Persist per-iteration loop state to GCS. | 2 | runner + sandbox | Tests actually **run** — the missing stage exists. |
| **P2 — assured loop** | Wrap `implement_plan` in generate→execute→measure→**gate** (build ∧ pass×5 ∧ +coverage). Codegraph = focal context. | 1 | Test Runner + Coverage Parser | Regression-safety by construction. |
| **P3 — real oracles** | Schemathesis conformance battery over the OpenAPI surface; metamorphic + differential relations; RESTler stateful/security checkers. | 3 | Schemathesis in exec | `assert 200` → contract-conformance + thousands of checks. |
| **P4 — critic & self-repair** ✅ BUILT (in-code) | QA-Critic (A2A peer or MCP tool) LLM-judge rubric; Reflexion loop; ensemble+vote on scenario gen. | 4 | +1 A2A peer *or* MCP tools | Scored, self-repaired output; evidence-based approval. |
| **P5 — self-heal & mutation** | Playwright Healer + triage/quarantine; mutation score (mutmut/PIT/Stryker) as final certification; fault-class-targeted negatives from insights (ACH). | 1, 2 | healer + mutation run | Adaptive UI runs + a *quality* number, not just coverage. |

> **Implementation status (2026-09-09).** **P0 + the in-code slice of P4 are BUILT** (no new infra;
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
> **Honest gap vs. the diagram:** with no execution stage yet (P1–P3), the loop's "measure" is the
> **judge rubric score**, *not* real coverage / flakiness×5 / mutation / schema-conformance. P1
> (Playwright/behave runner), P2 (real coverage gate), P3 (Schemathesis oracles) and P5 (self-heal +
> real mutation) remain **deferred** — each needs external infra / new deps / a new Cloud Run service.

**Constraints to respect (from this system's history):**
- Keep **one LLM call per iteration** — three serial blocking Vertex calls previously blew the Cloud Run
  liveness/request timeout. The Assured Loop is bounded and per-iteration, not per-turn.
- **Persist loop state to GCS** keyed by `context_id` — a Cloud Run redeploy has wiped in-flight memory-bank
  state before, forcing a full re-run. The loop must *resume*, not restart.
- **Human owns the final gate** — all auto-loops (assured/reflexion/ensemble/heal) are internal and bounded;
  the Claude client still asks Yes/No before approve / approve_plan, now with judge scores attached.
- **Ground in the codegraph** — focal context, producer–consumer inference, and fault targeting all read from
  the graphify codegraph the pipeline already builds.

---

## 5. Net picture

The pipeline stays **linear and human-gated on the outside**, but gains a bounded
**generate → execute → measure → gate → (self-heal) → judge → reflect → regenerate** inner loop, backed by a
**layered oracle stack** (schema/status/auth conformance + security checkers + metamorphic/differential +
visual-AI) and a **persisted quality score**. That closes all four gaps — no execution, no oracle, no
critic, no quality feedback — while reusing the existing MCP/A2A wiring, the GCS Memory Bank, and the
codegraph. The `.feature` we already export stops being an unrun artifact and becomes the entry point to a
real, self-correcting test run.

---

## 6. Caveats & source hygiene

- **Maintenance flags:** Qodo Cover is **"no longer maintained" (~2025)** — vendor/fork it, don't depend on
  upstream. **Dredd** (archived Nov 2024) and **Spring Cloud Contract** (archived) — prefer **Schemathesis**
  (conformance) and **Pact** (contracts). **jqwik** is in maintenance mode. **Octomind's** "discontinued for
  new customers" status is single-sourced/unverified.
- **Vendor claims** (Diffblue "100% compiling", mabl "80–99% heal", Skyvern WebBench 64.4%) are
  self-reported — directionally credible, not independently verified here.
- **Not open-sourced:** Meta **TestGen-LLM** and **ACH** are papers; Qodo Cover is the closest OSS proxy.
- **Metrics** treated as solid (cross-checked ≥2 sources): TestGen-LLM funnel (≈75% build / 57% pass
  reliably / 25% raise coverage / 73% engineer-accepted); coverage ≠ quality (100% cov / ~4% mutation).
- Star counts / versions are point-in-time (≈ Sept 2026). Two distinct "RESTGPT" projects exist — the one
  above is `selab-gatech/RESTGPT` (test tooling), *not* the unrelated "LLM-controls-REST-APIs" agent.

### Primary sources (selection)
TestGen-LLM https://arxiv.org/abs/2402.09171 · Qodo Cover https://github.com/qodo-ai/qodo-cover · CoverUp
https://arxiv.org/abs/2403.16218 · ChatUniTest https://arxiv.org/abs/2305.04764 · Meta ACH
https://arxiv.org/abs/2501.12862 · Playwright Test Agents https://playwright.dev/docs/test-agents ·
Playwright MCP https://github.com/microsoft/playwright-mcp · browser-use
https://github.com/browser-use/browser-use · Skyvern https://github.com/Skyvern-AI/skyvern · Stagehand
https://github.com/browserbase/stagehand · Healenium https://github.com/healenium/healenium · Schemathesis
https://github.com/schemathesis/schemathesis · RESTler https://github.com/microsoft/restler-fuzzer ·
EvoMaster https://github.com/WebFuzzing/EvoMaster · Hypothesis https://github.com/HypothesisWorks/hypothesis
· Pact https://docs.pact.io · Metamorphic testing survey https://dl.acm.org/doi/10.1145/3143561 · Reflexion
https://arxiv.org/abs/2303.11366 · Self-Refine https://arxiv.org/abs/2303.17651 · LLM-as-judge/MT-Bench
https://arxiv.org/abs/2306.05685 · G-Eval https://arxiv.org/abs/2303.16634 · DeepEval
https://github.com/confident-ai/deepeval · promptfoo https://github.com/promptfoo/promptfoo · MetaGPT
https://github.com/FoundationAgents/MetaGPT · Anthropic Building Effective Agents
https://www.anthropic.com/research/building-effective-agents · A2A https://a2a-protocol.org · MCP
https://modelcontextprotocol.io

---
*Compiled from four parallel deep-research sweeps (generation · execution/self-heal · API/property/contract ·
orchestration/oracles). Diagrams authored in Excalidraw; regenerate PNGs with the repo's
`render_excalidraw.py`.*
