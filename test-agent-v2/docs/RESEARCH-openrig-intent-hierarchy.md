# OpenRig's intent hierarchy + Refocus — investigation and debate against test-agent-v2

**Date:** 2026-09-24 · **Status:** design debate, no code changed · **Subject:**
`github.com/mvschwarz/openrig` read at `HEAD` (2026-09-24) vs. what test-agent-v2 has built.

### Diagram index

| # | diagram | what it argues | section |
|---|---|---|---|
| 1 | [`openrig-intent-concept`](openrig-intent-concept.png) | the two trees, composition direction, myth vs reality of Refocus | §2 |
| 2 | [`openrig-refocus-mechanics`](openrig-refocus-mechanics.png) | when a refocus fires, what content it resolves, what it delivers | §3 |
| 3 | [`openrig-scope-creep-controls`](openrig-scope-creep-controls.png) | the five controls that actually stop scope creep, mapped to us | §4 |
| 4 | [`openrig-compression-fidelity`](openrig-compression-fidelity.png) | the lossy pipeline, the silent deletion, the fidelity law | §5 |
| 5 | [`openrig-refocus-flow`](openrig-refocus-flow.png) | where intent leaks in our pipeline and where each move slots in | §6 |
| 6 | [`openrig-lore-vs-shared-memory`](openrig-lore-vs-shared-memory.png) | positional lore vs our shared bank, and the R0 break | §6.3–6.4 |
| 7 | [`openrig-maturity-ladder`](openrig-maturity-ladder.png) | the epistemic ladder vs our `Insight` fields | §6.4 |
| 8 | [`openrig-adoption-progress`](openrig-adoption-progress.png) | thirteen concepts scored, verdicts, build order | §7 |
| 9 | [`openrig-r2-drift-metric`](openrig-r2-drift-metric.png) | how R2 is computed, and the JEV upgrade path | §8 |

All `.excalidraw` sources sit beside the `.png` renders in this folder.

---

## 0. TL;DR

The intent hierarchy is real and maps onto us cleanly. Two corrections to the framing,
both load-bearing:

1. **Refocus is a delivery channel, not a validator.** It re-injects the intent chain at
   turn boundaries and asks three questions. Nothing computes "is this slice still needed."
2. **A one-line intent is explicitly NOT the mechanism.** openrig's fidelity law calls a
   one-line intent *"a ~20:1 lossy compression"* and requires the full design contract
   deposited INLINE in the leaf. An intent-sentence-per-altitude would be the anti-pattern.

The deepest hit is not the intent hierarchy at all — it is **`lore-routing.md`**, whose
founding rule is the exact thing we violated and then spent six mitigations undoing:

> The value is the combination of the content and where it was learned; **copying the
> bytes into a shared library destroys that distinction.**

Applying that lens to our code turned up a **live defect** (§6.4): the semantic arm of
`recall_lessons` can never return an auto-captured lesson.

| | move | cost |
|---|---|---|
| **FIX** | **R0** the `scope='shared'` recall dead-end (found by this review) | 1 line + a decision |
| **ADOPT** | **R1** route lesson recall by `origin_step` — the field we already write and never read | ~10 lines |
| **ADOPT** | **R2** the *drift* half of the coverage matrix: orphan + out-of-scope scenarios | ~30 lines, 0 LLM calls |
| **ADOPT** | **R3** refocus-on-rehydrate — a resumed session re-reads its brief | ~1 line per resume path |
| **REJECT** | **R4** slice-intent on `TestStep` | over-modelling; the scenario is the unit |
| **REJECT** | **R5** a periodic refocus hook/channel | 5 human gates + request-scoped runtime |
| **DEFER** | **R6** the maturity ladder + planning dial | real, but neither is a drift fix |
| **FREE** | **R7** CONTEXT-GAP / JUDGMENT-GAP on existing verdicts | one enum value |

And the inversion worth the whole document: **openrig's refocus asks the agent to
self-assess ("discomfort is the signal"). We own a calibrated judge. Ours can be measured.**

---

## 1. What openrig is

> *"A harness wraps a model. A rig wraps your harnesses."*

A multi-agent harness for teams of coding agents (Claude Code + Codex): tmux-backed
**seats** (a stable role and address, e.g. `dev-owner@first-project`), grouped into
**pods**, defined by `RigSpec`/`AgentSpec` YAML, on a Hono/SQLite daemon with CLI, TUI and
MCP surfaces. `CULTURE.md` sets coordination norms.

That is the runtime. Everything interesting for us is the **markdown control plane** above it.

## 2. The intent hierarchy — two trees

![The two trees, the composition direction, and what Refocus actually is](openrig-intent-concept.png)

The prompt's Project → Mission → Slice is correct, but it is **one of two trees**, and the
split is the point:

| tree | path | answers | ships? |
|---|---|---|---|
| **Topology** | instance → rig → pod → seat | *how work is done here* | **yes** — general defaults ship in source |
| **Project** | project → mission → slice | *what is being built* | **no** — *"shipping a default would install someone else's project as your context"* |

**The chain-file convention (CE-v2): one filename, identical at every altitude.** A reader
orients by walking from where they stand *toward the root*, reading the same-named file at
each level. No pointers to follow, no per-level names, no branching. Chain files sit on
**nodes** (rig, pod, seat; mission, slice) — never on shelves (`rigs/`, `missions/` are
containment, not nodes, and carry no chain file).

Names: topology carries `LEARNED.md` (what a **position** has learned) and `CULTURE.md`.
Project carries `SPEC.md`, `PROOF.md`, `PROGRESS.md`.

The composition rule:

> `SPEC.md` — **intent in frontmatter composes up the chain; specification is a leaf property.**

Intent is not restated per level — it *accumulates* as you walk to the root, and only the
leaf carries the concrete spec. Confirmed on both ends: `project.yaml` selects
`install.intent: SPEC.md`, and *"Mission and slice `SPEC.md` frontmatter supplies intent,
advisory sibling build-order `depends_on`, lifecycle status, and queue linkage hints."*

The precedence order is made concrete by the operating-posture resolver — the cleanest
statement of the altitude stack in the repo:

> qitem → workstream → mission → project → rig → global host

with qualifiers `qitem ID`, `project/mission/slice-id`, `project/mission`, `project ID`,
`canonical rig ID`, `null`. That is the intent hierarchy as an actual lookup chain.

And the rule that stops the hierarchy from becoming a liability — **the fidelity law**:

> A slice folder is ready when **SPEC.md alone, plus only what SPEC.md explicitly routes
> to, reproduces the design intent in a reader who has none of your context.**
>
> **A one-line intent is a ~20:1 lossy compression; building from it alone matches the
> design only by coincidence.** Design that happened in conversation is deposited at mint
> time or it dies with the author's context window.

## 3. Refocus — what it actually is

![How a refocus fires, resolves its content, and what it delivers](openrig-refocus-mechanics.png)

The prompt's description — *"makes the lower intent check if it's still needed to achieve
the higher intent"* — is the **spirit**. The mechanism is different, and the difference
decides what is worth building.

**Refocus is a delivery channel.** `openrig-core` ships `hooks/scripts/refocus.cjs`:

| event | Claude Code | Codex | why |
|---|---|---|---|
| `UserPromptSubmit` | ✓ | ✓ | deliver at a model-visible boundary |
| `Stop` | ✓ | — | catch a long turn crossing the growth threshold |
| `PostCompact` | ✓ | ✓ | retain compaction due-state; deliver next prompt |

Claude's extra firing signal is **transcript growth** — *not* turns (*"one turn can burn
200k tokens across fifty tool calls"*) and *not* wall-clock (*"the failure is sustained
work, not elapsed time"*). Default ≈2.6 MB of JSONL growth (≈300k tokens),
`OPENRIG_REFOCUS_BYTES` tunes it. Fresh `SessionStart` is always a no-op — onboarding owns
fresh orientation.

The premise, stated flatly, is the reason the thing exists at all:

> **Editing a file is not delivery.** A running seat read its configuration at session
> start, and nothing in its context re-reads disk on its own.

Delivered content: a path-only leaf→root trace of both chain trees
(`scripts/trace-to-root.py --trees both --depth light`), plus three questions:

> 1. What is the person actually trying to get? **Not your current task — the outcome.**
> 2. Does what you are doing RIGHT NOW move that? If you cannot say what a user gets, stop and say so.
> 3. What have you concluded **without opening the file or running the thing**?
>
> *Discomfort on any of these is the signal: **drift feels like work**.*

Two constraints worth copying verbatim:

- *"Your reads ARE the walk: a trace assembled from memory is a recitation that reproduces
  the drift it was meant to catch. **Run it; do not recall it.**"*
- *"A refocus corrects drift; it is **not a wake** (which restores liveness and must not
  reframe work) and **not a checkpoint** (a deliberate phase-boundary pause). Sending the
  heavy intervention when the light one was due is the most common self-inflicted stall."*

**So there is no automated "is this still needed" computation.** It is a scheduled
re-injection plus three self-asked questions. Cheap and honest — and precisely the seam
where we can do better, because we own a judge (§8).

## 4. Where openrig actually enforces anti-scope-creep

![The five controls, one per lifecycle stage, with our equivalent](openrig-scope-creep-controls.png)

Five mechanisms, none of them Refocus:

1. **Drift as a first-class review finding** (`wave-sdlc.md`). Reviewers review for drift,
   not only defects: *"is this still the doghouse the owner asked for, or did
   locally-defensible steps accrete toward a moon base? **Plot-loss is a first-class
   finding with the same standing as a logic defect.**"*

2. **Cause disposition — one word per miss.** CONTEXT-GAP (*the spec or its routes lacked
   what the moment needed — a planning finding; the fix lands in the spec*) vs
   JUDGMENT-GAP (*the context was there and the call was wrong — a builder finding; the fix
   is a check*). *"The rate this produces is the calibration the dispatch shape tunes on."*

3. **The A4 rule**, the sharpest sentence in the repo:
   > **Building the missing pieces inside the slice IS the scope creep.** Discovering them
   > and routing them is the slice working correctly — and a slice that reveals a real
   > product gap has produced something more valuable than the feature it set out to deliver.

   The honest response to a broken assumption is to revise the ambition DOWN, mark the
   slice PARTIAL, and name each missing capability **at source, with the file and line that
   proves it is absent**.

4. **Rigor priced per piece** — the planning dial P0–P4 (P0 pointers · P1 authored spec,
   the default · P2 + research *before* the spec freezes · P3 + adversarial pass · P4 +
   blind from-scratch design diffed against priors) and the wave as care dial. The
   discriminator is explicit and anti-intuitive: *"would a wrong plan be expensive, hard to
   undo, and invisible from inside"* — **never "is this piece central."**

5. **The context gate.** *"Only agents with the product's world context installed may author
   research prompts, run adversarial passes, or weigh in on architecture questions…
   research shaped by someone who does not know what the product is for returns answers to
   the wrong question, fluently."*

Plus the dispatch discipline that keeps intent alive through fan-out — **the brief is the
unit**, and *"THE BRIEF IS A MAP, NOT THE TERRITORY… the builder's first act is
self-onboarding from the routed reading list, then checking the map against the ground it
actually stands on."*

## 5. The two rules behind all of it

![The lossy compression pipeline, the silent deletion, and the fidelity law](openrig-compression-fidelity.png)

Both are about **compression loss**, which is the real subject of this comparison:

> The build is a **lossy compression pipeline**: product intent → planner spec → builder
> code, and each stage is a narrower reader than the one above. **Nothing leaks downward by
> proximity** — a dimension the owner's seat holds and does not WRITE AND ROUTE is deleted
> from the product, and **the deletion is silent: the downstream agent invents a plausible
> replacement rather than raising a hand.**

> **The spec is the router.** The downstream reader's world is SPEC.md; their curiosity
> does not extend past it, and **a file's existence is not a route**. Nothing load-bearing
> may depend on a reader's initiative.

Our pipeline is the same shape: ticket → pack → brief → plan → scenario → step → run. Six
compressions, each with a narrower reader. Every one of our documented seam bugs is an
instance of "the deletion is silent."

---

## 6. Our system, mapped honestly

![Where intent leaks in test-agent-v2 and where the four moves slot in](openrig-refocus-flow.png)

test-agent-v2 today: four A2A agents behind one MCP gateway — KGA (`gather`/`refine`),
TPD (`define`/`implement`), EXEC (`test_executor`), TEV (`test_evaluation`) — a two-tier
memory (GCS event log + Cloud SQL/pgvector), a JEV judge cascade, and a design-time
coverage matrix.

| openrig | our nearest thing | verdict |
|---|---|---|
| project → mission → slice | `context_id` run → `TestPlan` → `TestScenario` → `TestStep` | the chain exists as data; links are one-directional and optional |
| intent composes up the chain | `Pack.summary_text()`, `plan-brief.md`, `implement-brief.md` | **composes DOWN only** — no leaf re-derives its parent's purpose |
| the fidelity law (deposit design inline) | `plan-brief.md` + the 5 plan lists | **we already do the right thing here** — and a known bug undoes it (§6.2) |
| Refocus channel | *nothing*; re-aiming needs a fresh `context_id` | **missing** |
| `LEARNED.md` / lore is path-identified | `common/learn` + pgvector recall | **we store the position and never route by it** (§6.3) |
| maturity ladder + stage vocabulary | `confidence` + `status` + `supersedes` | partial; `supersedes` is a dead field |
| drift as a first-class finding | `CoverageMatrix` gaps | **we only measure under-coverage** (§6.1) |
| CONTEXT-GAP / JUDGMENT-GAP | `TriageVerdict(message, verdict)` on *execution* failures | we triage failed runs, never failed *plans* |
| planning dial P0–P4 | `TPD_ASSURED`, `TPD_LLM_DETAIL`, `depth=` | **binary env flags, deployment-global** — not per piece |
| the brief is the unit | `plan-brief.md` + `implement-brief.md` | **we have this, and it's good** |
| the two locks | `approve` / `approve_plan` client-owned gates | **we have this, and it's good** |

Five of these need their evidence spelled out.

### 6.1 The coverage matrix measures recall, never precision

`common/testplan/coverage.py` computes requirement × kind cells covered, code units reached,
and a gap report. Every number answers *"what's missing?"* **No number anywhere answers
"does this scenario serve anything?"** A scenario whose `source_refs` cite nothing, or cite
an unresolvable ref, is silently absent from `covered` and nothing reports it.

We already learned this asymmetry on the gather side — `recall=1.0, precision=0.00` is a
real state (complete-but-noisy), and reading only the leaked-node count hides it. We never
ported the lesson downstream.

### 6.2 The define→implement seam is "the deletion is silent", verbatim

Known behaviour: `define_plan(answer=…)` free-text corrections do not update the structured
In-scope / Passed-means brief fields, so the plan keeps its initial narrow shape. That is
exactly *"a dimension the owner holds and does not WRITE AND ROUTE is deleted from the
product… the downstream agent invents a plausible replacement rather than raising a hand."*

The same seam produced the `effective_kinds` incident, still documented in that function's
docstring: the implement fold-in collapsed `test_kinds` to `["performance"]` when it was
empty, which under the old `test_kinds or defaults` **silently dropped
happy/negative/boundary/error** and shipped a defaults-less suite. The fix was to make the
union ADDITIVE — a hardcoded guard at one seam, not a general rule.

### 6.3 We store the position and never route by it

![Positional lore vs a shared library, and the bug the missing axis hid](openrig-lore-vs-shared-memory.png)

`common/models/refine.py` `Insight` already carries `origin_step`, `scope`, `status`,
`supersedes`, `rationale`, `confidence`, `source_refs`. That is most of openrig's lore
frontmatter (`position`, `stage`, `method`, `date`) **already in our schema**.

But:
- `origin_step` is **write-only** — set in `capture.py`, projected into pg `meta`, asserted
  in two tests, and **read by no recall path**. `recall_lessons` filters on
  `source_refs ∩ seed_refs` and sorts by confidence/recency. The position is never consulted.
- `supersedes` is declared in the dataclass and referenced **nowhere else in `src/`**.
- Recall **copies the statement bytes** into `Pack.lessons` → `summary_text()`. openrig:
  *"An attachment never embeds or copies the lore bytes"* — an attachment is a pointer plus
  the owning position, resolved on demand under an explicit grant.

This is the concrete cause of the KGA memory-bleed (deployed `refine` asking ZIP-import
questions for a *billing* ticket): lesson bytes earned at one position were composed into
another position's context with no positional filter. Our response was B0–B6 — six
statistical dampers (pack-scoped `run_id`, thin-seed parent climb, codegraph focus anchor,
topic-coherence stop, IDF hub penalty, a structural grounding gate, exclude re-anchor).

openrig never needed any of them because lore is **path-scoped by construction**.

### 6.4 A live defect this review found: the semantic recall arm is dead

Applying the positional lens surfaced a real bug, not a design gap:

- `common/learn/capture.py:30` hardcodes `scope="context"` on **every** auto-captured lesson.
- The semantic leg of recall filters `scope='shared'` — `common/memory/pg/store.py:203`
  (`WHERE status='active' AND scope='shared' AND kind IN ('lesson','correction','gotcha')`)
  and `common/memory/vector_memory.py:204` (the same predicate).
- Nothing in `src/` ever writes `scope="shared"`. The only occurrence is a test fixture,
  `tests/test_index_projector.py:73`.

**Therefore the vector/semantic arm of `recall_lessons` cannot return an auto-captured
lesson.** Only the structural arm (edge → `seed_refs`) can return anything. The generic
`search` path is unaffected — it passes `scopes = ["context", "shared"]` — so this is
specific to lesson *recall*.

One line to fix, but decide the semantics deliberately rather than flipping the default.
`scope` is our `taxonomy`/privacy class, and openrig's answer is that crossing from
position-local to shared is **an authored graduation event with a recorded warrant**, never
a default. Making capture write `"shared"` would be exactly the laundering that convention
forbids. The right fix is for recall's semantic leg to accept `("context", "shared")` like
every other query, and to keep a real promotion path for anything that should go wider.

*(Live confirmation still wanted: the two-tier rollout recorded "cross-lingual recall
proven", which likely exercised `search_nodes` or the structural arm. Worth re-checking
against `recall_lessons` specifically before assuming the semantic leg ever fired in prod.)*

The `scope` field is one rung of a trust model openrig makes explicit and we only half-have.
Their epistemic ladder is what `scope`, `confidence`, `status` and `supersedes` are each a
fragment of — which is why two of those four fields are currently dead:

![The epistemic ladder, and our Insight fields against it](openrig-maturity-ladder.png)

The mapping is closer than expected — `rationale` **is** openrig's warrant, and `status` is
correctly a separate lifecycle axis from trust. The three gaps are that `confidence` is a
flat grade rather than a ladder with promotion/demotion events, `scope` is hardcoded and
never promoted, and `supersedes` is dead where openrig requires a successor pointer on
anything superseded.

### 6.5 A resumed session rehydrates state but not intent

`RoundSession._rehydrate` (`common/testplan/session.py`) restores `pending`, `open_carried`,
`raised`/`answered`, decisions and current questions — and reloads the pack in the ctor. It
**never re-reads `plan-brief.md`**. The assured loop resumes from its GCS checkpoint the
same way.

That is openrig's premise sitting in our code, and it lands on exactly our long-running
paths: `implement_plan` is chunked multi-turn, `run_suite` is polled/chunked, the assured
loop is GCS-checkpointed to survive a Cloud Run kill.

---

## 7. The debate

**Motion: adopt openrig's intent hierarchy and Refocus into test-agent-v2.**

### FOR

1. **We have paid for drift twice, on the record** — the wrong-ticket refine bleed, and
   `recall=1.0 / precision=0.00` on LUZ-159312 where all five "grounded external-LLM leads"
   were cross-project AI/agent-framework meta pages. Both are "the lower unit stopped
   serving the higher intent."
2. **The coverage matrix is half-built and we know which half.** Orphan/out-of-scope
   counters are an inverse index over data we already persist.
3. **Our resumable paths are exactly openrig's failure case** (§6.5) — a hole in shipping
   code, not a hypothetical.
4. **Most of the schema already exists.** `origin_step`, `scope`, `supersedes`, `rationale`
   are in `Insight` today. This is wiring, not modelling.
5. **Fan-out makes it urgent** (§9).

### AGAINST

1. **openrig's altitudes are org-shaped; ours are artifact-shaped.** openrig has agents
   holding seats for days, and drift accrues because nobody re-reads. Our pipeline is one
   gated chain per ticket with a **client-owned human Yes/No at refine, approve,
   define_plan, approve_plan and implement_plan**. The human *is* the refocus channel and
   fires five times per run. Automating a refocus into a five-gate pipeline is ceremony.
2. **Slice-intent on a Gherkin step is over-modelling** — and openrig's own SOP says so:
   *"If you're spending more time on the convention files or the audit than on the running
   product, stop and go build. Running the full apparatus on a small change is the
   letter-worship failure, not diligence."*
3. **Naming it "Refocus" doesn't make it new.** Half of R2 is a reindex of `covered`. Say
   so in the diff, or we grow a subsystem where a function belongs.
4. **Any refocus that costs an LLM call breaks I3.** Implement is deliberately *one* LLM
   call; three serial blocking Vertex calls already blew past Cloud Run's request timeout
   and got an instance killed. A refocus must be deterministic, ride an existing call, or
   not exist.
5. **The intent-sentence idea is wrong by openrig's own standard.** The fidelity law says a
   one-line intent is ~20:1 lossy. We already deposit the design inline via `plan-brief.md`.
   Adding a thin `TestPlan.intent` string would be the *anti-pattern* — and worse, it would
   invite downstream code to read the cheap field instead of the brief.

### Verdict — applying openrig's own "price one layer lower"

![Thirteen concepts scored, with verdicts and the build order](openrig-adoption-progress.png)

Their right-layer check is the honest way to settle this:

> Before accepting the fix your hands reached for, price ONE LAYER LOWER. **The bone tell:**
> the lower fix collapses several open problems at once, and is often SMALLER than the patch
> — it deletes or reuses instead of adding. **The band-aid tell:** the lower layer is
> stable, correct, and merely inconvenient.

The fix our hands reached for is *an intent hierarchy*. One layer lower is **positional
routing of knowledge we already store**. That layer shows every bone tell: it collapses the
memory-bleed class, it explains why B0–B6 were needed, it is *smaller* than what it
replaces, and it reuses `origin_step` instead of adding a field. Argument 5-against kills
the intent-sentence outright. So:

**R0 — fix the `scope='shared'` recall dead-end. DO IT FIRST.** §6.4. One line in the
predicate, plus a deliberate decision about what graduation to shared should mean.
Everything else about memory is unmeasurable until the semantic arm can return something.

**R1 — route lesson recall by `origin_step`. ADOPT** (this replaces the intent-sentence
idea). `recall_lessons` gains a position filter: a lesson earned at `gather` is recalled for
`gather`, not for `define`. The field is already written on every lesson. This is openrig's
lore convention in its smallest honest form, and it attacks the documented bleed at the
layer the bleed actually lives on.

**R2 — the drift half of the coverage matrix. ADOPT.** Two numbers beside
`requirement_pct` in `CoverageMatrix`:
- `orphan_scenarios` — scenarios whose `source_refs` resolve to no requirement unit;
- `out_of_scope_hits` — scenarios whose title/description token-match `plan.out_of_scope`
  (`_tokens` already exists in that file).

Deterministic, zero LLM calls, renderable in the existing gap section. **openrig's
plot-loss finding as a number, and the highest-value item here.**

**R3 — refocus-on-rehydrate. ADOPT.** On resume (`RoundSession._rehydrate`, the assured
loop's GCS resume), re-read `plan-brief.md` into the working context. Not a hook, not a
schedule, not a threshold — *a resumed session re-reads its intent*. The smallest possible
form of openrig's premise.

**R4 — slice-intent on `TestStep`. REJECT.** The scenario is the unit.

**R5 — a periodic refocus hook/channel. REJECT.** Cloud Run request handlers are not seats
with 300k-token transcripts, and five human gates already do this job. Revisit if EXEC ever
grows a genuinely autonomous multi-hour loop — at which point copy the *transcript-growth*
trigger, not turns and not wall-clock.

**R6 — the maturity ladder and the planning dial. DEFER, but record what they expose.**
Two real smells: `supersedes` is a dead field where openrig requires a successor pointer on
anything superseded; and `TPD_ASSURED` is a **deployment-global env flag** deciding how much
rigor *every* ticket gets, when rigor is obviously a per-piece property. Both are config /
lifecycle refactors, not drift fixes. Do not let them ride in on this change.

**R7 — CONTEXT-GAP vs JUDGMENT-GAP. STEAL, it's free.** One field on `TriageVerdict` and on
the assured loop's `issues`. It answers a question we have argued repeatedly and never
measured: *when a scenario is wrong, do we fix the pack (gather) or the prompt
(generation)?* One word per finding; the **rate** is the calibration signal.

---

## 8. The inversion — we can beat the mechanism we're copying

![How R2 is computed, and the JEV upgrade path](openrig-r2-drift-metric.png)

openrig's refocus is *self-asked*: three questions, and "discomfort on any of these is the
signal." That is the right design for a harness that owns no judge, and it is honest about
being unmeasurable.

**We own a calibrated judge.** JEV returns a bare `noul` float — P(true) — and already
fronts failure triage in EXEC and the source gate in gather; the κ-calibration work exists
precisely to make those numbers trustworthy.

So R2's upgrade path is not "add an LLM refocus." It is: once the deterministic orphan /
out-of-scope counters exist and are reported, promote them to a **gated cascade** —
`P(this scenario serves the plan intent)` through the JEV path we already ship, run **once
per implement pass over the merged scenario set** (never per scenario, never per turn — I3
stands). Cheap deterministic filter first, judge only the residue. The same shape as every
gate we already have.

**openrig asks the agent whether it has drifted. We can measure it.** That is the one place
this comparison should end with us ahead.

## 9. Where the multi-agent risk actually lands

The prompt's framing — *"the more agents you have, the more scope creep could happen"* — is
right, and it is worth being precise about where it bites.

**It does not bite scenario generation.** Phase-C worker fan-out (`TPD_GEN_MODE=workers`,
Pub/Sub + Cloud Run workers; the coordinator splits the pack into per-batch jobs and merges
results) fans out over *scenarios within one plan*. Every worker shares one intent. No
divergence is possible.

**It bites gather.** Documented behaviour: sequential `gather_codebase(repo, ctx)` calls
stop grounding once the exploration converges — the second repo returns 0 nodes and
"budget/round-limit reached" — and the remedy is `repo=` up front or a **fresh context per
repo**. That is literally *different builders, different intents, one shared context →
noise*, with a context reset as the only cure.

So the forward-looking case for the intent chain is **multi-repo / multi-source parallel
gather**, not plan generation. When a gather leg is dispatched per repo, each leg needs its
own intent composing up to the run's — and openrig's answers apply directly: the brief is
the unit, territories are exclusive, self-onboard from the routed reading list, then check
the map against the ground. That is also the moment to revisit R5.

One caution from openrig on the multi-tester question specifically — do **not** hand each
tester a narrow aperture on purpose:

> Agents inevitably narrow… **the narrowing IS the specialization effect** — the system's
> core mechanism, never a flaw to correct. Widening a specialist diffuses what made them
> elite. **Never set a narrow aperture intentionally**; seats arrive at theirs on their own.
> The ONLY aperture you ever steer is the wide one.

The corollary is their wire protocol, which is free and which our orchestrator violates
whenever it over-specifies a worker prompt:

> Empowerment is delivered as **context, never as instructions** — in both directions. An
> orchestrator that converts context into step-by-step orders bypasses the builder's
> synthesis.

## 10. Free to steal — sentences, not mechanisms

- *"The build is a lossy compression pipeline."* Ours has six stages. **Nothing leaks
  downward by proximity.**
- *The measuring stick:* **SPEC.md alone, plus what it explicitly routes to, reproduces the
  intent in a reader with none of the author's context.** Apply that to `plan-brief.md` as a
  review question today, with no code.
- *"A file's existence is not a route."*
- *"Editing a file is not delivery."* Our version: publishing to the prompt store, or
  redeploying MCP instructions, does not refresh a running session.
- *"Canon without warrants is cargo cult with good formatting."* Our `rationale` field is
  the warrant — treat it as required, not optional.

---

## Sources

All openrig content read directly from the repository at `HEAD`, 2026-09-24, via the GitHub
contents API; quotations are verbatim first-party. **Web search was blocked in this session
by an org policy (`constraints/vertexai.allowedPartnerModelFeatures`)**, so no secondary
corroboration was possible — treat third-party claims about openrig as unverified; the
quotations themselves are from source.

- `README.md` — rigs, seats, pods, culture, stack, commands
- `docs/reference/chain-file-convention.md` — CE-v2, the two trees, intent composing up the chain
- `docs/reference/refocus-channel.md` — the hook, events, thresholds, content ladder
- `.../skills/refocusing/{SKILL.md,references/refocus.md}` — the three questions, the trace script
- `docs/reference/sdlc-conventions.md` — Parts A/B, the component menu, A4, the elastic middle
- `docs/reference/wave-sdlc.md` — the care dial, plot-loss, CONTEXT-GAP vs JUDGMENT-GAP
- `docs/reference/planning-dial.md` — P0–P4, the context gate, what earns P2/P3
- `docs/reference/product-management-pass.md` — the fidelity law, the spec as router, aperture, price-one-layer-lower
- `docs/reference/lore-routing.md` — position knowledge by address, the outward gate
- `docs/reference/knowledge-maturity.md` — the epistemic ladder, stage vocabulary, the warrant rule
- `docs/reference/project-workspace.md` — `install.intent`, the workspace contract
- `docs/reference/scoped-operating-posture.md` — the qitem→…→global precedence chain
- `.../skills/mission-slice-sop/SKILL.md` — Part A in practice, proportionality

Our side verified in code at `024018d`: `common/testplan/models/{plan,scenario}.py`,
`common/testplan/coverage.py`, `common/testplan/session.py`, `common/models/refine.py`,
`common/learn/{model,capture,recall,govern}.py`, `common/memory/{retrieve,vector_memory}.py`,
`common/memory/pg/store.py`, `test_plan_definition/implement/{assured,generate}/`,
`test_executor/runners/suite.py`.
