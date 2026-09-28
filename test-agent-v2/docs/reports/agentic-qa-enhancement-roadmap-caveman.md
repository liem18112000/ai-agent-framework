# agentic-qa-enhancement-roadmap.excalidraw — Caveman Explain

**Big idea: four research-backed upgrade rocks bolted onto the pipeline robot ALREADY has.
Each pillar say exactly WHERE it plugs in. The big missing rock = a real "(Test execution)"
stage — build it, and the red cliff go away.** 🧱🔬🚀

*(This the v2 doc set. The enhancement map is framework-neutral.
Names kept current; no new architecture invented here.)*

---

## The top line — CURRENT PIPELINE 🔵🟣⬜🔴

Claude owns every Yes/No gate, one context_id threads the whole hunt:
**gather_knowledge → refine → approve → define_plan → approve_plan → implement_plan → get_scenarios → .feature**
Then the red dashed box: **(Test execution) — NOT BUILT YET**. That the cliff. Bold numbers under a stage = which pillar upgrades it.

## PILLAR 1 — Assured Test Generation 🟢

Replace the single LLM call with **generate → run → measure → keep-only-if-it-helps**.
Rocks: Meta TestGen-LLM (assured filter) · Qodo Cover-Agent · mutmut/PIT/Stryker (mutation = the quality gate) · ChatUniTest · SWE-agent/Aider (run-fix-rerun template).
**Plugs into `implement_plan`** — wraps the one-shot call in the Assured Loop.

## PILLAR 2 — Real Test Execution + Self-Healing 🟠

Build the missing "(Test execution)" stage: run the .feature, heal on break, triage.
Rocks: Playwright (+bdd/behave) · Playwright MCP (a11y-tree, ~300 tok/step) · Playwright Test Agents (Planner·Generator·Healer) · browser-use/Skyvern/Stagehand · Healenium · Applitools (visual oracle).
Pattern: **agent discovers once → compile to deterministic code → agent heals only on failure.**
**Plugs into NEW stages after get_scenarios** — fills the red cliff.

## PILLAR 3 — API Oracle Stack 🔵

Turn heuristic "assert 200" into thousands of spec-checked cases with REAL oracles (API-first).
Rocks: Schemathesis (property-based from OpenAPI) · RESTler (stateful fuzz) · Hypothesis/EvoMaster · Metamorphic + Differential (oracle-free when no ground truth) · Pact (contracts).
**Plugs into the execution / assert layer** — works with Pillar 2.

## PILLAR 4 — Critic · Judge · Reflexion 🟣

Add a verifier + self-repair loop so scenario quality is SCORED, not assumed.
Rocks: LLM-as-judge (G-Eval/DeepEval/promptfoo) · Reflexion/Self-Refine · Ensemble + voting · Faithfulness/groundedness (Ragas/TruLens) · a new QA-Critic (A2A peer OR MCP tool, same context_id).
**Wraps `implement_plan`; runs before the human Yes/No gate** — evidence-based approval.

## SHARED SUBSTRATE — wiring nobody changes ⬜

Bottom grey band, every new stage reuses it: GCS Memory Bank (notes·index·runs·graphify **+NEW** traces·healed-locators·scores·reflections) · Vertex AI (Claude) generators · MCP + A2A · Codegraph = focal context.

## Rock color meaning 🎨

- 🔵 **blue** = the pipeline itself · Pillar 1 gen-stages / Pillar 3 API oracle
- 🟢 **green** = Pillar 1 (Assured Test Generation) panel
- 🟠 **orange** = Pillar 2 (Real Execution + Self-Heal) panel
- 🟣 **purple** = define/approve/implement stages · Pillar 4 (Critic·Judge·Reflexion) panel
- 🔴 **red dashed** = the NOT-BUILT-YET execution cliff · ⬜ **grey** = shared substrate + get_scenarios

## One grunt takeaway

**Four pillars, four research-grounded OSS toolkits, each mapped to an exact plug-point.**
Biggest hole = the real execution stage (Pillar 2) — build that and the red cliff close.
Pillars 1 & 4 both hug `implement_plan`; Pillar 3 lives in the assert layer. 🦣🧱👍
