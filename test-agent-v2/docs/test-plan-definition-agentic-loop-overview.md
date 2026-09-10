# Test-Plan Definition Agent — Agentic Loop (Manager Overview)

**Scope:** `test-agent-v2/src/test_plan_definition` — Step 3+4 of the Testing Agent.
**Audience:** manager / architecture overview (the *shape* of the loop and the
decisions that drive it, not a line-by-line walkthrough).
**Source:** code trace, refreshed 2026-09-10 to match the interrogative build (Q1–Q5).

![TPD agentic loop — manager overview](./test-plan-definition-agentic-loop.png)

> **Diagram note:** the PNG still shows the earlier *3-round define + one-shot implement*
> shape; the text below is current (4-round define + interrogative implement + coverage
> matrix). Diagram refresh pending.

---

## TL;DR

The Test-Plan Definition (TPD) agent turns an **approved insight pack** (from the
knowledge-gathering agent) into an **executable BDD test suite**. It does this
with a single agentic loop over one shared `context_id`:

> **DEFINE** (interrogate the human, **4 rounds**) → **APPROVE** (lock the plan)
> → **IMPLEMENT** (interrogate the *artifacts*, then generate data + scenarios + steps).

Both phases are now **interrogative** — the agent asks the human the judgement calls
rather than guessing them — and the generated suite is scored against a **coverage
matrix**. Everything is persisted to a shared **GCS memory bank**, and the whole thing
is served as one Cloud Run service that speaks both **A2A** (agent-to-agent JSON-RPC)
and **MCP** (the tools Claude calls).

---

## 1. The manager / control plane

Three tiers, one request path. The client never touches business logic directly —
it drives the loop through a fixed tool surface.

| Tier | What it is | Key entry points |
|------|-----------|------------------|
| **MCP bridge** | The 6 tools Claude calls | `define_plan`, `approve_plan`, `implement_plan`, `get_plan`, `get_scenarios`, `get_coverage` |
| **A2A router** | A prefix-verb router + orchestrators | `define` / `approve` / `implement` / `get-test-plan` / `get-scenarios` / `get-coverage`; nests a `define` agent and an `implement` **orchestrator** |
| **GCS memory bank** | Shared, durable state | `memory/test-plan/<ctx>/` |

- The bridge forwards every tool call to the agent as an A2A **`message/send`
  (JSON-RPC 2.0)**; the same `context_id` threads all the way from gather → refine
  → define → implement, so no state is passed by hand.
- Long LLM calls run **off the event loop** (`asyncio.to_thread`) so a multi-second
  Vertex call never starves Cloud Run's `/livez` probe and gets the instance killed.
- **The client owns every confirm gate.** Before starting define, before approve,
  and before each implement round, Claude asks the human a Yes/No — the agent never
  auto-advances.
- **The router is state-aware.** A live define or implement interrogation routes the
  next answer-turn back to the right sub-agent automatically (it reads `state.json` /
  `implement-state.json`), so multi-turn interrogation "just works" over the flat tool
  surface.

---

## 2. The agentic loop

### Phase A — DEFINE (interrogate the plan)

A multi-turn interrogation, one round per human turn, over exactly **four** rounds,
in order:

1. **methodology** — API / E2E / UI (default: API)
2. **scope** — feature in/out of scope + one question per integration touched
3. **metrics** — what "passed" means + the coverage bar
4. **test-design** — *which test-design method(s) to use* — the agent **suggests** the
   method from the feature's shape (a lifecycle/state machine → state-transition;
   an eligibility/pricing matrix → decision table; many parameters → pairwise; several
   dependencies → error-path; risk markers → risk-based depth; always EP+BVA as the base)
   and from the earlier three rounds, then asks the human to accept / change / **add**.

The engine is a simple ask/pause cycle: `generate_round` produces the round's
questions (via the LLM when Vertex is configured, else a heuristic strategy), the
agent **pauses** (`requires_input`), the human answers with `define_plan(answer=…)`,
and the answer is distilled into a `PlanDecision` (a human answer is a high-confidence
*decision*; an agent self-answer is a low-confidence *assumption*).

> **Design note — the stop condition is structural, not confidence-gated.** The
> loop advances **one round per human turn** and stops when the four rounds are
> exhausted. There is no "am I confident enough?" gate deciding whether to ask
> more. Confidence is computed only at the end and merely sets the plan's status.

**Output:** a `TestPlan` (`methodology`, `scope`, `out_of_scope`, `metrics`,
**`test_design`**) plus a human-readable `plan-brief.md`. Status is `confirmed` if
there are no open gaps, otherwise `draft`.

### Gate — APPROVE (lock)

`approve_plan` is the reconfirm gate. There is **no separate lock object** — it
simply flips `TestPlan.status` to `confirmed`. **The status field *is* the lock.**
A `draft` plan (with unresolved open gaps) is blocked from implementation until
approve force-confirms it.

### Phase B — IMPLEMENT (interrogate the artifacts, then generate)

Interactive implement is now an **orchestrator** (`ImplementOrchestrator`) that nests
two sub-agents and runs them in sequence over the turns:

```
implement  ─▶  interrogate  (case-design → data-design → step-oracle)  ─▶  generate
                └ an ImplementSession mirroring the define PlanSession        └ data → scenarios → steps → .feature
```

**Interrogate** asks the QA/QC judgement calls the one-shot path used to guess:

- **case-design** — *which test KINDS to cover.* The four defaults (happy / negative /
  boundary / error) are only a seed; the round **asks the human to add more** (security,
  performance, concurrency, compliance, accessibility, i18n, migration…). The answer
  updates the plan's **open `test_kinds`** taxonomy.
- **data-design** — valid/invalid partitions + boundary values; which dependencies are
  stubbed vs hit for real; fixtures.
- **step-oracle** — the oracle each case asserts (end-state / side-effect vs `assert 200`)
  + teardown + negative assertions.

Once the design is confirmed, the orchestrator chains into **generate** (the same
one-shot generator, now driven by the elicited kinds):

**test data → scenarios → steps → Gherkin `.feature`**

> **Design note — one LLM call by default (unchanged).** Interrogation is
> heuristic (no model). In generation, only **scenarios** calls the LLM, and only when
> `VERTEX_*` is configured; **test-data** and **steps** are heuristic unless
> `detail=True` / `TPD_LLM_DETAIL`. This is the deliberate fix for the "three serial
> Vertex calls blew the Cloud Run timeout" bug — still enforced.

> **No caps.** The old closed `happy × negative × boundary × error` over ≤8 notes
> (≤ 32 scenarios) is gone. Kinds are the **open** elicited set, cases per kind are
> **uncapped**, and every grounded behaviour is enumerated — the count is driven by the
> coverage goal, not a constant.

**Two overlays wrap generation:**

- **Assured loop (opt-in, `assured=True` / `TPD_ASSURED`).** Replaces the single blind
  scenario call with a bounded *generate → LLM-as-judge → gate → reflect → regenerate*
  loop; the score rides on the reply and is checkpointed (`assured.json`) so a Cloud-Run
  kill resumes, not restarts. Default OFF keeps the single call.
- **Coverage matrix (always).** After scenarios are written, a **codegraph-driven
  coverage matrix** is built: requirement units (notes + insights) + code units
  (codegraph **endpoints + hubs**) × the open kinds, with a **traceability + gap report**
  and a coverage %. Read it with `get_coverage`.

**Output:** `get_scenarios` returns `scenarios.md` (BDD/Gherkin) which the client renders
into the final HTML artifact; `get_coverage` returns the traceability/gap report.

> **Autonomous path stays one-shot.** The opt-in end-to-end `SequentialAgent` pipeline
> (gather → refine → define → approve → implement) can't do human-in-the-loop, so it
> uses the one-shot `ImplementAgent` directly — interrogative implement is the
> *interactive* default only.

---

## 3. State machine

```
draft  ──approve_plan──▶  confirmed  ──implement (interrogate → generate)──▶  implemented
```

Three coupled states drive the lifecycle: **`TestPlan.status` {draft | confirmed}**,
the resumable **define session `state.json` {done}**, and the resumable
**implement session `implement-state.json` {done}**. There is no separate `implemented`
flag — implementation is evidenced by the written scenario artifacts + coverage matrix
plus the run-log.

---

## 4. What lands in GCS

All TPD artifacts live in a **separate namespace** from the knowledge-gathering
agent's (`memory/refine/<ctx>/`), keyed by the same `context_id`:

```
memory/test-plan/<ctx>/
  questions.json  answers.json  decisions.json          # define interrogation trail
  plan.json  plan.md  plan-brief.md                     # the plan (+ test_design) + human brief
  implement-state.json  implement-decisions.json  implement-brief.md   # implement interrogation
  test-data.json  scenarios.json  scenarios.md  steps.json
  features/<name>.feature                               # BDD export
  assured.json                                          # P4 assured-loop checkpoint (when enabled)
  coverage.json  coverage-matrix.md                     # Q5 coverage matrix + gap report
  state.json                                            # resumable define session
memory/runs/<ts>_plan-<run_id>.md                       # run-log
memory/graphify/<repo>/latest/…                         # codegraph the matrix reads (shared registry)
```

The shared knowledge graph also gains `TEST_PLAN` + `TEST_SCENARIO` nodes with
provenance edges back to the source notes/insights. Read-back always goes through
the **JSON sidecars** (schema-drift tolerant); the `.md` files are
presentational / write-only.

---

## 5. Manager takeaways

- **Interrogative, resumable loop.** The agent asks the human the judgement calls in
  both phases (4-round define + 3-round implement) and every turn is persisted, so a
  dropped session resumes from `state.json` / `implement-state.json`.
- **Agent-recommended, human-confirmed.** The test-design round *suggests* the method
  from the feature's shape; the case-design round *proposes* kinds and invites more.
  The human always accepts / changes / adds — nothing is silently assumed.
- **No coverage cap; a real gap number.** Open kind taxonomy + uncapped cases + a
  codegraph coverage matrix mean "aim for 100%" has a concrete, closeable target
  (`get_coverage`), not a fixed 32-scenario ceiling.
- **Cheap + Cloud-Run-safe by default.** Interrogation is model-free; generation is one
  LLM call by default (`detail` / `assured` opt into more) — the serial-Vertex timeout
  guard is intact.
- **Human stays in control.** Client-owned Yes/No gates + status-as-lock mean nothing
  gets generated off an unapproved plan.
- **Natural extension point (Q6).** The loop authors a scored, traced suite but stops at
  *design-time* coverage. The obvious next stage is **executing** the `.feature` and
  replacing the design-time proxy with real executed coverage + mutation — the proposed
  **Test Executor agent** (`RESEARCH-test-executor-agent.md`), which the coverage matrix
  is explicitly built to hand off to.
