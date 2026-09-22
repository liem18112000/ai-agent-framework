# Test Executor Agent — the missing execution stage (Pillars 2 & 3)

**Purpose.** Design a **new A2A agent** — the **Test Executor** — that turns the Gherkin `.feature` the
Test-Plan Definition (TPD) agent already exports into a *real, self-correcting test run*. It scopes the two
enhancement pillars that live **downstream of `implement_plan`**: **Pillar 2 — Real Test Execution +
Self-Healing** and **Pillar 3 — the API Oracle Stack**. Every claim is anchored to a source URL; concepts
are tabulated. **This is a design report — the agent is not built yet.**

> **Split note (2026-09-10).** Split out of the former `RESEARCH-agentic-qa-enhancements.md`. Its
> generation-side half — **Pillars 1 & 4** (assured generation, critic/judge/reflexion), delivered *inside*
> the TPD agent and already **BUILT in-code** — lives in
> [`RESEARCH-tpd-assured-generation.md`](./RESEARCH-tpd-assured-generation.md). The two are companions: TPD
> **generates and self-critiques**; the Executor **runs and self-heals**.

> **Diagrams (open in Excalidraw, PNGs render inline):**
> - The Assured Test Loop (the EXECUTE / MEASURE / self-heal / oracle band is this agent) — [`agentic-qa-assured-loop.excalidraw`](./agentic-qa-assured-loop.excalidraw) · [`.png`](./agentic-qa-assured-loop.png)
> - Enhancement roadmap (all phases P0–P5, both agents) — [`agentic-qa-enhancement-roadmap.excalidraw`](./agentic-qa-enhancement-roadmap.excalidraw) · [`.png`](./agentic-qa-enhancement-roadmap.png)

> **Companion reports.**
> - Upstream generator — [`RESEARCH-tpd-assured-generation.md`](./RESEARCH-tpd-assured-generation.md).
> - Scoring the TPD output — [`RESEARCH-tpd-evaluation-adk-testsuite.md`](./RESEARCH-tpd-evaluation-adk-testsuite.md).

---

## 0. TL;DR — the `.feature` is currently an unrun artifact

**Where we are.** The pipeline is `gather → refine → approve → [evaluate_pack] → define_plan →
approve_plan → implement_plan → get_scenarios → [evaluate_plan]`. `implement_plan` exports a Gherkin
`.feature` "for the downstream Test execution stage" — **and that stage does not exist.** The pipeline
generates (now *scored*, per the TPD doc) scenarios, then **stops**: no execution, no run→fix→rerun loop,
no self-healing, no verifier/critic *at runtime*, no real test oracle, no coverage/quality feedback from a
real run.

**The field's answer.** The entire post-2024 agentic-testing field converges on one shape: **don't emit a
test you haven't run.** Generate a candidate → execute it → measure a signal → keep it only if it provably
helps → feed failures back → repeat. Two mature pillars fill the downstream gap:

| # | Pillar | Closes the gap of… | Delivered by |
|---|--------|--------------------|-----------|
| **2** | **Real Test Execution + Self-Healing** | no execution, no heal, no triage | **the new Test Executor agent** |
| **3** | **API Oracle Stack** | heuristic `assert 200`, no real oracle | the Executor's assert layer (API-first) |

> **Status: design-only.** The Executor is a **proposed 5th A2A agent**, sibling to knowledge-gathering,
> test-plan-definition and test-evaluation. Everything below is the target; nothing here is implemented.

---

## 1. Concepts & terms (glossary)

### 1.1 Execution & self-healing (Pillar 2)

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

### 1.2 API / property / spec / contract testing (Pillar 3)

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

---

## 2. The repo & framework landscape

Maturity/stars are point-in-time (≈ Sept 2026) and approximate. **Maintenance flags matter** — see §6.

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
| **SWE-agent / mini-swe-agent** | https://github.com/SWE-agent/SWE-agent · https://github.com/SWE-agent/mini-swe-agent | reference *agentic run→observe→fix* loop; mini is a ~100-line template | MIT |
| **Aider** | https://aider.chat/docs/usage/lint-test.html | AI pair-programmer with an auto lint/test loop (runs tests, feeds errors back, auto-fixes) | Apache-2.0 |
| **OpenHands** | https://github.com/All-Hands-AI/OpenHands | autonomous SWE/QA agent (writes code, runs tests, verifies) | MIT |

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

---

## 3. Target architecture (patterns)

### 3.1 Execution + self-healing — *the missing stage*
→ [`agentic-qa-assured-loop.png`](./agentic-qa-assured-loop.png)

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

### 3.2 API oracle stack — *real oracles instead of `assert 200`*

The single biggest oracle upgrade needs only the OpenAPI surface the services already expose:

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

### 3.3 The agent shape — *how the Executor fits the existing wiring*

A 5th A2A agent, keyed by the **same `context_id`** as the rest of the pipeline, reusing the MCP gateway,
the GCS Memory Bank and the codegraph:

- **A2A Agent Card** (proposed tools): `run_suite(context_id)` — run the persisted `.feature`;
  `heal_step(context_id, step_id)` — replay+patch one failing step; `triage_run(context_id)` — classify
  failures; `get_run_report(context_id)` — read-only results. Register them on the gateway exactly as the
  KGA/TPD/TEV tools are.
- **Pipeline seam:** slots in **after `get_scenarios`** — `… → implement_plan → get_scenarios → run_suite →
  [triage/heal] → get_run_report`. Optional and read-model-friendly, like `evaluate_plan`.
- **Sandbox:** the runner executes in an isolated sandbox (browser + network egress controlled). *Not* in
  the agent request path — a job the agent kicks off and polls, to stay off the Cloud Run request timeout.
- **State / resume:** per-iteration run state persisted to GCS under `context_id` (`run.json`, traces) so a
  Cloud Run kill **resumes, not restarts** — the same discipline the TPD assured loop uses.
- **Human-gated heals:** every locator/data patch a Healer proposes goes through the client's existing
  **Yes/No gate** — never a silent retarget (it can mask a real regression).
- **Feeds the assured loop:** the Executor's real signals (coverage delta, flakiness×5, schema-conformance,
  mutation kills) become the ②–③ *MEASURE* inputs the TPD [Assured Loop](./RESEARCH-tpd-assured-generation.md)
  currently stands in for with a judge score — closing that honest gap.

---

## 4. Enhancement roadmap (Executor phases)
→ [`agentic-qa-enhancement-roadmap.png`](./agentic-qa-enhancement-roadmap.png) (full P0–P5, both agents)

Each phase is independently shippable. All are **design-only / deferred** — each needs external infra:

| Phase | What | Pillars | New infra | Payoff |
|-------|------|---------|-----------|--------|
| **P1 — execution backbone** ⏸ | Playwright + `playwright-bdd`/`behave` runs the `.feature`; Playwright MCP binds steps. Persist per-iteration loop state to GCS. | 2 | runner + sandbox + new A2A service | Tests actually **run** — the missing stage exists. |
| **P3 — real oracles** ⏸ | Schemathesis conformance battery over the OpenAPI surface; metamorphic + differential relations; RESTler stateful/security checkers. | 3 | Schemathesis in exec | `assert 200` → contract-conformance + thousands of checks. |
| **P5 — self-heal & mutation** ⏸ | Playwright Healer + triage/quarantine; mutation score (mutmut/PIT/Stryker) run against the real suite; fault-class-targeted negatives from insights (ACH). | 1, 2 | healer + mutation run | Adaptive UI runs + a *quality* number, not just coverage. |

**Constraints to respect (from this system's history):**
- **Keep the run off the request path** — three serial blocking Vertex calls once blew the Cloud Run
  liveness/request timeout; a full test run is far heavier. Kick off a job, poll, persist — don't block.
- **Persist run state to GCS** keyed by `context_id` — a Cloud Run redeploy has wiped in-flight state
  before. The run must *resume*, not restart.
- **Human owns the final gate** — heals/quarantines are surfaced for Yes/No, never silent.
- **Ground in the codegraph** — producer–consumer inference and focal targeting read from the graphify
  codegraph the pipeline already builds.
- **Credentials & network** — the runner needs test-env creds + controlled egress the read-only agents
  never had; treat the sandbox as a distinct trust boundary.

---

## 5. Net picture (Executor scope)

Adding the Executor turns the exported `.feature` from an **unrun artifact** into the entry point of a real,
self-correcting run, backed by a **layered oracle stack** (schema/status/auth conformance + security
checkers + metamorphic/differential + visual-AI) and a **persisted run report**. It closes the two
downstream gaps — no execution, no real oracle — and back-fills the *MEASURE* signals the upstream
[TPD Assured Loop](./RESEARCH-tpd-assured-generation.md) needs to move from a judge-score proxy to real
coverage/flakiness/mutation gating. The pipeline stays **linear and human-gated on the outside**; the
Executor adds a bounded **run → measure → (self-heal) → triage** inner loop.

---

## 6. Caveats & source hygiene

- **Maintenance flags:** **Dredd** (archived Nov 2024) and **Spring Cloud Contract** (archived) — prefer
  **Schemathesis** (conformance) and **Pact** (contracts). **Octomind's** "discontinued for new customers"
  status is single-sourced/unverified. **jqwik** is in maintenance mode.
- **Vendor claims** (mabl "80–99% heal", Skyvern WebBench 64.4%) are self-reported — directionally credible,
  not independently verified here.
- **Two distinct "RESTGPT" projects exist** — the one above is `selab-gatech/RESTGPT` (test tooling), *not*
  the unrelated "LLM-controls-REST-APIs" agent.
- **New trust boundary:** unlike the read-only KGA/TPD, the Executor holds test-env credentials and makes
  live calls / drives a browser — the biggest security delta of this agent; sandbox it.
- Star counts / versions are point-in-time (≈ Sept 2026).

### Primary sources (selection)
Playwright Test Agents https://playwright.dev/docs/test-agents · Playwright MCP
https://github.com/microsoft/playwright-mcp · browser-use https://github.com/browser-use/browser-use ·
Skyvern https://github.com/Skyvern-AI/skyvern · Stagehand https://github.com/browserbase/stagehand ·
Healenium https://github.com/healenium/healenium · Schemathesis
https://github.com/schemathesis/schemathesis · RESTler https://github.com/microsoft/restler-fuzzer ·
EvoMaster https://github.com/WebFuzzing/EvoMaster · Hypothesis https://github.com/HypothesisWorks/hypothesis
· Pact https://docs.pact.io · Metamorphic testing survey https://dl.acm.org/doi/10.1145/3143561 ·
AgentCoder/CodeT https://arxiv.org/abs/2312.13010 · https://arxiv.org/abs/2207.10397 · A2A
https://a2a-protocol.org · MCP https://modelcontextprotocol.io

---
*Split from the former `RESEARCH-agentic-qa-enhancements.md` (2026-09-10). Generation-side pillars (1 & 4)
in [`RESEARCH-tpd-assured-generation.md`](./RESEARCH-tpd-assured-generation.md). Diagrams authored in
Excalidraw; regenerate PNGs with the repo's `render_excalidraw.py`.*
