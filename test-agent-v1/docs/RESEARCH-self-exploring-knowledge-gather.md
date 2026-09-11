# Self-Exploring Knowledge Gather — Research → Enhancement Report

**Purpose.** Companion to [`RESEARCH-agentic-qa-enhancements.md`](./RESEARCH-agentic-qa-enhancements.md),
which is entirely **test-plan / execution-side** (its four pillars all wrap `implement_plan` and add the
missing test-*execution* stage). This report covers the **first** agent instead: turning the **Knowledge
Gathering Agent (KGA)** from a *deterministic link-follower* into a **self-exploring researcher** that can
start from a **blank / thin issue — a title and nothing else** — and actively reach three source tiers to
assemble a grounded pack:

1. **Internal** — the agent's own GCS Memory Bank (prior gathers + confirmed insights).
2. **Atlassian** — Jira & Confluence, but by **search** (JQL / CQL), not only by pre-existing links.
3. **External** — the public internet (web search) and a public LLM (e.g. Gemini) as a **lead generator**.

Same house style as the sibling report: TL;DR + principle, a glossary, the current anatomy and its exact
gaps, a target architecture, a phased roadmap, and constraints drawn from this system's own history.

> **Diagram (open in Excalidraw, PNG renders inline):**
> - The Self-Exploration Loop — [`self-exploring-knowledge-gather.excalidraw`](./self-exploring-knowledge-gather.excalidraw) · [`.png`](./self-exploring-knowledge-gather.png)
>   The loop now carries a **TIERS 5·6·7 — LIVE GCP ESTATE (NEW)** band (see §8).

> **Extension — reach the live cloud estate (tiers 5/6/7).** The three source tiers below are all
> *document* sources. A companion plan adds three **operational** tiers that ground the pack in what is
> actually deployed and running — service discovery across every env, expanding-window log inspection, and
> service-to-service communication mapping — via one GCP-explore sub-agent riding the same seams. See
> [`../../test-agent-v2/docs/PLAN-gcp-service-exploration-tiers.md`](../../test-agent-v2/docs/PLAN-gcp-service-exploration-tiers.md)
> · [`.excalidraw`](../../test-agent-v2/docs/gcp-service-exploration-tiers.excalidraw) and §8 below.

---

## 0. TL;DR — the one gap and the one principle

**Where we are.** `gather_knowledge(seed)` runs a bounded, concurrent **frontier crawl**:
`Seed → Fetch → Extract → Classify → Expand → Distill → Persist`, bounded by `depth / max_nodes /
max_seconds` (`loop/crawl.py`). It **fetches and follows** four node kinds — `jira`, `confluence`,
`bitbucket`, `codegraph` (`_fetchable`), and only *pushes to the frontier* the links a node **already
contains** (issue-links, remote-links, dev-panel PRs/commits, Confluence children). `external-web`, `figma`,
`google-doc` are **classified and recorded but never fetched** (`classify_url` → not in `_fetchable`). The
Memory Bank is written during a crawl and read on demand via the `search_memory` / `get_note` MCP tools —
but the crawl itself **never consults memory**.

**The gap.** The crawl can only ever discover what is **already linked from the seed**. Give it a **thin
issue** — a Jira ticket with a title and no description, no links, no dev panel — and it returns **~1 node and
stops**. (Your own memory notes call this out: *"a 0-links crawl is a false-negative, not an empty ticket"*;
the parent/dev-panel fix pushed one such crawl from 1 → 15 nodes, but only because those links *existed*.)
There is **no hypothesis-from-title, no query generation, no Atlassian search, no external reach, and no
memory reuse.** The agent cannot *explore*; it can only *traverse*.

**The field's answer — the gather-side principle.** Where the test side's rule is *"don't emit a test you
haven't run,"* the gather-side rule is:

> **Don't stop at the seed. From whatever you have — even just a title — form hypotheses, query the
> cheapest trusted source first, promote confident hits to new seeds, run the existing crawl on them,
> and converge when the marginal yield drops. Cite every fact to a source; treat the external LLM as a
> lead generator, never as a source of truth.**

That is Retrieval-Augmented **exploration**: the deterministic crawl stays as the *executor*, wrapped in an
agentic **hypothesize → fan-out → promote → converge** loop that feeds it seeds from three source tiers.

| # | Source tier | Trust / cost | Today | Target |
|---|-------------|--------------|-------|--------|
| **1** | **Internal memory** (GCS index + insights) | verified · free | read-only tool, *not* in the crawl | **self-seed** + dedup + reuse prior insights |
| **2** | **Atlassian search** (JQL / CQL) | authoritative · cheap | only pre-existing **links** followed | **search** from title+hypotheses → promote hits to seeds |
| **3a** | **External web** (search + fetch) | verifiable · metered | classified, **never fetched** | make `external-web` fetchable; grounded + cited |
| **3b** | **External LLM** (e.g. Gemini) | **unverified** · cheap breadth | absent | **lead generator only** → grounded back before pack entry |
| **5** | **GCP discover** (Cloud Asset Inventory) | authoritative · metered | absent | enumerate deployed services across every env × platform → promote `gcpsvc:` seeds |
| **6** | **GCP logs** (Cloud Logging) | authoritative · metered | absent | read each service's logs over an **expanding window** 7→14→21→28 d until *enough* |
| **7** | **GCP relate** (log · config · trace) | authoritative · metered | absent | infer service-to-service communication edges → the crawl walks the service graph |

> Tiers **5/6/7** are the *operational* peers of the document tiers above — same hypothesize→ground→promote→crawl
> loop, but the source is the **live GCP estate** instead of documents. Full design in §8 /
> [`PLAN-gcp-service-exploration-tiers.md`](../../test-agent-v2/docs/PLAN-gcp-service-exploration-tiers.md).

---

## 1. Concepts & terms (glossary)

The vocabulary for the rest of the report. (Where a term already appears in the sibling report — *agentic
vs deterministic*, *Reflexion*, *LLM-as-judge* — it is reused, not redefined.)

| Term | Definition | Why it matters here |
|------|-----------|---------------------|
| **Thin / blank seed** | A seed node that yields little or nothing to expand on: a Jira ticket with a title but no description, no links, no dev panel. | The trigger for self-exploration. A thin seed today ends the crawl at ~1 node — a false-negative. |
| **Hypothesis generation** | From the little text available (title, labels, component), infer *what the change is about* — the likely subsystems, entities, features, and prior tickets. | The bridge from "a title" to "things to search for." Cheaply done by one LLM call over the title + memory context. |
| **Query expansion** | Turn one hypothesis into many concrete queries: JQL/CQL search strings, web-search phrases, code symbol names. | One title → a dozen probes across three tiers. The fan-out step. |
| **Retrieval tiering (cost/trust ladder)** | Query sources cheapest-and-most-trusted first (memory → Atlassian → web → LLM), spending the expensive/less-trusted tiers only when the cheaper ones fall short. | Bounds cost and keeps the pack in-domain; the external LLM is the last resort, not the first. |
| **Self-seeding from memory** | Before crawling, query the GCS index for prior nodes/insights matching the seed's terms; add high-confidence matches as `extra_seeds` and as prior-knowledge context. | Reuse beats re-gather. "We tested a similar ticket before" is the cheapest possible source. |
| **Seed promotion** | A discovered candidate (a Jira key from a JQL hit, a Confluence id, a URL) is *promoted* to a real seed and pushed onto the crawl frontier — subject to the same `in_scope` / dedup / budget rules. | The seam that lets search results re-enter the existing deterministic crawl unchanged. |
| **Source triangulation / corroboration** | Prefer a claim supported by ≥2 independent sources (e.g. a Confluence spec **and** the code); down-weight single-source, especially LLM-only, claims. | Turns breadth into reliability; the antidote to acting on one unverified hit. |
| **Grounding & citation (provenance)** | Every note carries the exact source it came from (`source_url`, `origin`); nothing enters the pack without a traceable origin. | The pack is the *test basis*. An ungrounded fact becomes a wrong test. Provenance also lets the human prune. |
| **Lead generator vs. source of truth** | The external LLM's output is treated as **hypotheses and search queries**, never as facts written into the pack. Its leads must be *grounded* in a verifiable source (Jira/Confluence/code/web) before acceptance. | The single highest-risk design decision. Skipping this injects hallucinated requirements into the test basis. |
| **Grounding gate** | The checkpoint that rejects any candidate fact lacking a verifiable, fetchable source — LLM leads that can't be corroborated are dropped (or demoted to "unconfirmed lead"). | Where the "lead generator" rule is enforced in code. |
| **Marginal-yield / convergence stop** | Stop exploring when a new round adds few/no *new in-scope* nodes (or the budget is spent), not at a fixed depth. | Blank issues need adaptive breadth; a fixed `depth=2` under- or over-explores. |
| **Coverage-of-the-ask (recall) vs. precision** | *Recall*: did we find everything relevant to the ticket? *Precision*: is what we found actually relevant? Self-exploration trades one for the other. | A wide crawl is not automatically a good crawl; `Scope` + `in_scope` + convergence bound the drift. |
| **Reflection to memory** | On a weak or empty result, write a verbal note ("title too vague; searched X,Y; found nothing in web tier") to the Memory Bank under `context_id`, and use it to steer the next round. | Reflexion (sibling §1.4) applied to *retrieval*, not generation. Makes the loop learn within a session. |
| **JQL / CQL** | Jira Query Language / Confluence Query Language — text + field search over the two Atlassian corpora. | The mechanism for Tier 2. The current Jira/Confluence clients fetch *by id*; they need *search* endpoints. |
| **RAG framing** | Retrieval-Augmented Generation: retrieve relevant context, then let the model act on it. Here the "generation" is the interrogation/insight step downstream; gather is the *retrieval*. | Names what the KGA already is and what it should become — a retriever that actively searches, not only follows. |

---

## 2. Where we are — KGA anatomy & the exact gaps

### 2.1 The current crawl (what works)

`loop/crawl.py` is a clean, bounded frontier crawl and should **stay** — it is the deterministic *executor*
the self-exploration loop wraps:

- **Seed normalization** (`loop/seed.py::normalize_seed`): `LUZ-123` → `jira:`, digits → `confluence:`,
  URL → `classify_url`, `<ws>/<repo>` → `codegraph:`.
- **Per-kind fetchers** (`loop/fetch/*`, `NodeFetcher` registry, Open/Closed): `jira`, `confluence`,
  `bitbucket`, `codegraph`. Adding a source = drop a `NodeFetcher` subclass + import it — **no change to
  `fetch_node`**. This is the extension point the whole plan below rides on.
- **Expansion is link-following only**: a node's `LinkRecord`s are pushed to the frontier iff
  `lr.in_scope and _fetchable(lr.canonical_url)`. `Scope.follow_types = (JIRA_ISSUE, CONFLUENCE_PAGE)`.
- **Bounded & fault-tolerant**: `depth / max_nodes / max_seconds`; a fetch failure becomes a **declared gap**,
  never a silent drop; each depth level is fetched concurrently under a semaphore.
- **Persist + memory**: notes upserted to the GCS bank; the link-graph index updated; a `RunLog` appended.

### 2.2 The three gaps, mapped to your three tiers

| Requirement (your ask) | Current behaviour | Precise gap |
|---|---|---|
| **Blank issue → guess & find** | Crawl starts from a concrete seed and follows only *existing* links. | No **hypothesis-from-title** and no **query generation**. A thin seed → ~1 node → stop. No recovery path for the known "0-link false-negative." |
| **Atlassian (Jira, Confluence)** | ✅ Fetched and followed — but only links already present on a node. | No **JQL/CQL search**. The Jira/Confluence clients fetch *by id* only; they can't answer "find issues/pages about `<title terms>`." |
| **External (internet, Gemini/LLM)** | `external-web` / `figma` / `google-doc` are **classified and recorded, never fetched** (`_fetchable` excludes them). | Entire external tier absent from the crawl. No web fetch, no external-LLM call. |
| **Internal (agent memory)** | `search_memory` / `get_note` exist as **manual read-only MCP tools**. | The crawl never **self-seeds from memory** or reuses prior insights; memory is write-during-crawl, read-on-demand. |

### 2.3 What must NOT change

- **The human gate stays.** Self-exploration only *widens the candidate pack*; `refine → approve` still gate
  what becomes the test basis. Every discovered node must carry **provenance** so the human can prune.
- **The deterministic crawl stays.** New tiers feed it *seeds*; they don't replace `crawl.py`.
- **Codegraph grounding stays** (standing rule): a discovered repo still routes through
  recommend → user-confirm → build, not auto-clone.

---

## 3. Target architecture — the Self-Exploration Loop

See the diagram beside this file. In words: a bounded controller wraps the existing crawl and, when the seed
is thin (or on demand), runs **hypothesize → fan-out across three tiers → ground → promote → crawl →
reflect → converge**.

```
        thin/blank seed (title, labels, component)
                │
   ① HYPOTHESIZE ─ one LLM call over title + memory context → likely
        │          subsystems / entities / features / prior tickets
        ▼
   ② EXPAND ─ hypotheses → concrete queries per tier
        │
        ├─▶ TIER 1  Memory (GCS index)      search_memory(terms)  ── cheapest, verified
        ├─▶ TIER 2  Atlassian search        JQL(title) · CQL(title)
        ├─▶ TIER 3a External web            WebSearch → fetch → distill  (cited)
        └─▶ TIER 3b External LLM (Gemini)   enumerate leads/terms ─┐ (NOT facts)
                │                                                  │
                ▼                                                  ▼
   ③ GROUND ── grounding gate: keep a candidate IFF it resolves to a       ◀── LLM leads must
        │       fetchable, citable source (jira/confluence/web/code).           ground here or drop
        ▼       triangulate: ≥2 sources ⇒ high confidence.
   ④ PROMOTE ── survivors → canonical seeds → the existing crawl frontier
        │        (unchanged in_scope / dedup / budget rules)
        ▼
   ⑤ CRAWL ──── loop/crawl.py runs as today over the promoted seeds
        │
        ▼
   ⑥ REFLECT ── new in-scope nodes this round? ── yes ─▶ back to ① (refined hypotheses)
        │        write reflection + provenance to Memory Bank under context_id
        └ no / budget spent ─▶ CONVERGE → pack (+ declared gaps) → refine (human gate, unchanged)
```

### 3.1 Tier 1 — Internal memory (self-seed & reuse) · *lowest effort, highest certainty*

Before the crawl, query the GCS index (reuse `executor/memory.py::run_search_memory` logic) for prior nodes
and **insights** whose id/title/type match the seed's terms. High-confidence matches are (a) added as
`extra_seeds`, and (b) surfaced to the interrogation as *prior knowledge* ("this looks like LUZ-158390,
which we tested; reuse its scope"). No new infra — memory already exists; it's just not *consulted* by gather.
**Caveat:** the shared GCS knowledge-index is a read-modify-write hotspot; concurrent gathers can race
(see the parallel-orchestration note) — self-seed reads are safe, but keep index writes single-writer.

### 3.2 Tier 2 — Atlassian search (JQL / CQL) · *biggest in-domain win for blank issues*

Add **search** to the Atlassian clients (`common/atlassian/jira.py`, `confluence.py`) — `search_jql(text)`
and `search_cql(text)` — and a thin **expander** that builds queries from title + hypotheses (component,
labels, key phrases, `text ~ "..."`, `summary ~ "..."`). Hits are returned as candidate `jira:` / `confluence:`
ids and **promoted** to seeds. This is what actually rescues a blank ticket: the title *"Export fails for
restricted folders"* has no links, but a CQL/JQL sweep finds the spec page and the sibling bug. Implement
either as a pre-crawl step or as a new `NodeFetcher` for a `jira-search:` / `confluence-search:` pseudo-kind
that emits `LinkRecord`s (fits the Open/Closed registry with zero change to `fetch_node`).

### 3.3 Tier 3a — External web (search + fetch) · *make `external-web` fetchable*

Promote `external-web` from *recorded* to *fetchable*: a `WebFetcher` that runs a web search over the
query, fetches the top results, and distills them like any other node — **with citation** (`source_url`
preserved, `origin="web-search"`). Add `external-web` (and, when needed, `google-doc`) to a widened
`_fetchable` **and** to a new outbound `Scope` gate so web nodes are followed only when explicitly enabled
(they must not blow the budget by default). Every web fact is cited; uncitable content is dropped.

### 3.4 Tier 3b — External LLM (Gemini) · *lead generator, never source of truth*

An `ask-llm:<query>` expander that asks a public LLM to **enumerate** likely subsystems, domain terms,
related feature names, and plausible edge cases for the title. Its output is parsed into **candidate queries
and seeds only** — it is fed *back into Tiers 1–3a*, never written into the pack as fact. The **grounding
gate (③)** then keeps a lead only if it resolves to a real Jira/Confluence/web/code source; unresolved leads
are dropped or demoted to an explicit "unconfirmed lead" the human can chase. This is the safeguard that
keeps hallucinated requirements out of the test basis. (Mirror the sibling report's LLM-as-judge caution:
use a *different* model family from the one that later generates scenarios, to avoid compounding one model's
blind spots.)

### 3.5 The controller — bounded, resumable, one LLM call per round

The loop is the agentic capstone (analogue of the sibling's Assured Loop). Design rules it must obey:

- **One blocking LLM call per round** (the hypothesize step), offloaded to a thread — three serial blocking
  Vertex calls previously blew the Cloud Run liveness/request timeout.
- **Per-tier sub-budgets** on top of the existing `max_nodes / max_seconds`; a slow/failed tier degrades to a
  **declared gap**, never a hang (the crawl already turns fetch failures into gaps — extend the same
  discipline to searches and web fetches).
- **Persist loop state to GCS keyed by `context_id`** so a Cloud Run redeploy **resumes**, not restarts (a
  redeploy has wiped in-flight memory-bank state before, forcing a full re-run).
- **Convergence, not fixed depth**: stop when a round adds no new in-scope nodes or the budget is spent.

---

## 4. Enhancement roadmap (phased)

Ordered lowest-effort/highest-certainty → highest-assurance. Each phase is independently shippable and each
tightens the blank-issue story. Mirrors the sibling report's P0…P5 shape.

| Phase | What | Tier | New infra | Payoff |
|-------|------|------|-----------|--------|
| **G0 — memory self-seed** | Before crawl, `search_memory(title terms)`; add high-confidence prior nodes/insights as `extra_seeds` + prior-knowledge context. | 1 | none | Reuse beats re-gather; instant lift on repeat/near-dup tickets. |
| **G1 — Atlassian search** | `search_jql` / `search_cql` from title+hypotheses; promote hits to `jira:` / `confluence:` seeds when the seed is thin. | 2 | client search endpoints | **Blank issues stop returning 1 node.** Biggest in-domain win. |
| **G2 — hypothesize step** | One LLM call: title (+ memory) → subsystems/entities/related tickets → query set that drives G1. | 1,2 | 1 Vertex call/round | Turns "a title" into targeted searches; grounds G1's queries. |
| **G3 — external web** | Make `external-web` fetchable: WebSearch → fetch → distill, cited; gated by an outbound `Scope` flag + sub-budget. | 3a | web egress + fetcher | Reaches specs/docs/standards outside Atlassian; still grounded. |
| **G4 — external LLM leads** | `ask-llm` expander (Gemini/Vertex) enumerates leads → fed back to Tiers 1–3a; **grounding gate** before pack entry. | 3b | +1 LLM route | Breadth on sparse tickets *without* injecting hallucinations. |
| **G5 — self-exploration controller** | Bounded `hypothesize → fan-out → ground → promote → crawl → reflect → converge`; resumable GCS loop state; marginal-yield stop; reflection to memory. | all | loop state in GCS | Adaptive, self-correcting gather — the agentic capstone. |

**Constraints to respect (from this system's history):**
- **One LLM call per round**, thread-offloaded — serial blocking Vertex calls previously killed the Cloud
  Run instance (`ERROR_TIMEOUT`).
- **Persist loop state to GCS** keyed by `context_id` — a redeploy must **resume**, not restart.
- **Everything cited; nothing ungrounded.** The external LLM is a *lead generator*; the grounding gate is
  mandatory, not optional. The pack is the test basis — an ungrounded fact is a wrong test.
- **Human owns the gate.** Self-exploration widens the candidate pack; `refine → approve` still decide what
  counts. Attach **provenance** (which source, which query, which tier, single- vs multi-source) to every
  discovered node so the human can prune with evidence.
- **Bounded & degrading.** Every tier has a sub-budget and fails to a **declared gap**, never a hang.
- **Codegraph grounding stays** — a discovered repo routes through recommend → confirm → build.
- **Mind the shared-index RMW race** — self-seed reads are safe; keep index writes single-writer.

---

## 5. Net picture

The KGA stays a **bounded, human-gated, deterministic crawler on the inside** — but gains an agentic
**hypothesize → fan-out → ground → promote → crawl → reflect → converge** shell that feeds it seeds from a
**three-tier source ladder** (verified memory → authoritative Atlassian search → cited external web →
grounded external-LLM leads). A **blank issue with only a title** stops being a dead-end: the agent forms
hypotheses, searches every reachable source, corroborates across sources, promotes confident discoveries to
the frontier, and converges when the yield dries up — **citing every fact and refusing to write down anything
it cannot ground.** That closes the gather-side gaps — no self-start, no search, no external reach, no memory
reuse — while reusing the existing `NodeFetcher` registry, the `Scope`/`in_scope`/budget machinery, the GCS
Memory Bank, and the human gate. The pack that reaches `refine` stops being "whatever happened to be linked"
and becomes "what the agent could find and verify about the ask."

---

## 6. Caveats & source hygiene

- **The external LLM is the highest-risk element.** Treating its output as fact — instead of as leads to be
  grounded — would inject hallucinated requirements straight into the test basis. The grounding gate (§3.4)
  is load-bearing, not a nicety. Use a *different* model family from the downstream scenario generator.
- **Precision ≠ recall.** A wider crawl is not automatically a better one; blank-issue exploration can drift
  off-topic. `Scope`, `in_scope`, triangulation, and the convergence stop are what keep breadth honest —
  tune them, and prefer *provenance-visible* over-collection (human prunes) to silent under-collection.
- **Cost & egress.** Tiers 3a/3b add API + network cost and new egress paths; gate them behind flags
  (follow the existing default-off pattern, e.g. `TPD_LLM_DETAIL`) and per-tier sub-budgets.
- **Shared-index concurrency.** Self-seeding reads the GCS knowledge index that concurrent gathers may be
  rewriting (RMW race) — reads are safe; keep writes single-writer.
- **Not a replacement for the crawl.** This report *wraps* `loop/crawl.py`; it does not rewrite it. The
  deterministic frontier remains the executor.

### Primary sources (selection)
This report is grounded in **this repository's own code and history** rather than external papers; the
retrieval/agentic patterns it borrows are cross-referenced to the sibling report:
- Current crawl & fetchers — `test-agent/src/knowledge_gathering/loop/{crawl,seed}.py`,
  `loop/fetch/{__init__,base,jira,confluence,bitbucket,codegraph}.py`,
  `common/extract/classify.py`, `common/models/graph.py`.
- Memory read tools — `knowledge_gathering/executor/memory.py`; MCP surface —
  `knowledge_gathering/bridge/mcp_server.py`.
- Retrieval / agentic patterns (RAG, Reflexion, LLM-as-judge biases, agentic-vs-deterministic, grounding) —
  see [`RESEARCH-agentic-qa-enhancements.md`](./RESEARCH-agentic-qa-enhancements.md) §1.4 and its primary
  sources (Reflexion, Self-Refine, ReAct, LLM-as-judge/MT-Bench, Anthropic *Building Effective Agents*).
- Operational constraints — the project memory notes on the Cloud Run timeout, GCS state loss on redeploy,
  the shared-index RMW race, the codegraph grounding rule, and the "0-link false-negative" smell.

---

## 7. Field report — memory-bias drift (LUZ-159312) and the de-bias phases

*Added after running the live pipeline on **LUZ-159312**. This is the empirical confirmation of the §6 caveat
"**Precision ≠ recall** — blank-issue exploration can drift off-topic." It did — in a specific, instructive way,
and the fix is now evidenced, not hypothesized.*

### 7.1 What happened

`LUZ-159312` ("Functional Test & Performance test") is a **thin container**: a title, a parent
(`LUZ-156281` = *credit-card-only billing for individual clients — remove QR fallback, dunning & failed-charge
notifications*), and seven subtasks — with **no acceptance-criteria body of its own**. The real spec lives one
hop up, in the parent.

Run against a Memory Bank **saturated with ePost ZIP-import** content from prior sessions, the self-exploration
loop (G2–G5) drifted off-seed round by round, and `refine` then interrogated an entirely different ticket:

| | Ungrounded (`run-b40487cb`) | Grounded on `luz_finance` (`run-aeafff37`) |
|---|---|---|
| round 0 focus | "Functional Test & Performance test" — on-topic | same — on-topic |
| round 1 focus | "… **epost zip import**" — drift | "… **luz_finance** automation tests" — on-topic |
| round 2 focus | "**2021-02-02 klara documents weekly**" — off-topic | *(converged — no round 2)* |
| result | **43 nodes**, mostly ZIP-import | **12 nodes**, on-topic, **converged** |
| `refine` output | ZIP-import / `transfer.zip` metadata questions, citing **`LUZ-158390`** (a different ticket) | *(bypassed — see B0)* |

Same seed. The **only** difference is that the grounded run carried a strong on-seed anchor (the `luz_finance`
codegraph); it stopped drifting and converged. **That contrast is the whole diagnosis: the loop needs a strong
on-seed anchor and must distrust generic memory recall.**

![Memory-bias drift in the self-explore loop — an ungrounded thin-seed run (top) drifts round by round into the ePost ZIP-import memory "gravity well" and yields a 43-node wrong-domain pack, while a codegraph-grounded run (bottom) stays on-seed and converges to a 12-node luz_finance pack.](./self-explore-memory-bias.png)

> **Diagram source** (edit in Excalidraw; regenerate the PNG with `render_excalidraw.py`): [`self-explore-memory-bias.excalidraw`](./self-explore-memory-bias.excalidraw)

### 7.2 Why it happens (the mechanism)

1. **A thin seed carries no gravity of its own.** With almost no own-text, the seed can't dominate the focus,
   so whatever the round's query terms happen to match takes over.
2. **Generic query terms match the dominant memory domain.** "Functional test", "performance", "automation
   tests" are domain-neutral — they cosine-match the ZIP-import test pages that flood the bank, not the billing
   feature.
3. **The Memory Bank is a gravity well.** One domain (ePost ZIP-import) dominates the bank from prior sessions,
   so recall over-returns it for *any* thin testing seed — a **hub-domain over-recall** effect (the same class
   as a high-degree hub dominating a graph walk).
4. **Drift compounds.** Each round's focus is computed from the *accumulated pack*; once round 1 admits
   ZIP-import nodes, round 2 anchors on *them*, not the seed — the well deepens.
5. **`refine` reads the global bank, not the pack.** Even the correctly-grounded pack was ignored: the deployed
   interrogation pulls from memory, so it asked ZIP-import / `LUZ-158390` questions regardless of grounding.

### 7.3 The de-bias roadmap (B-phases)

Ordered cheapest/highest-certainty → structural, mirroring the §4 G-table. Each phase targets one mechanism
above and is independently shippable.

| Phase | Fixes | What | Effort | Payoff |
|-------|-------|------|--------|--------|
| **B0 — scope `refine` to the pack** | #5 | `refine`/`define` interrogate the `context_id`'s own node set only; forbid the global Memory Bank as the question corpus. | low | The wrong-ticket questions vanish; every other fix becomes *visible* downstream. **Do first.** |
| **B1 — thin-seed → climb, don't recall** | #1 | Detect low-own-content seeds; expand via the **structural hierarchy** (parent AC, subtasks, epic, dev-panel) *before* any memory recall. | low | The real spec (`LUZ-156281`) drives exploration instead of memory. |
| **B2 — codegraph anchor at round 0** | #1,#2 | Resolve the seed's dev-panel repo → build/attach its codegraph in round 0 and feed it into **every** round's focus. | med | Empirically converged the run; the single strongest corrective. |
| **B3 — topic-coherence stop** | #4 | Score each round's focus distance from the **seed** (not the growing pack); discard/stop a round past threshold. Convergence = "on-topic **and** dry", not just "no new nodes". | low-med | Kills the round-2 drift; makes "don't stop at the seed" safe. |
| **B4 — hub-penalty de-bias (IDF)** | #3 | Down-weight memory nodes/domains that match **many unrelated** seeds (BM25/IDF rarity); cap any single domain's share of a round's promotions. | med | The structural fix — pays off on every future ticket as the bank grows. |
| **B5 — grounding gate on *promotions*** | #2 | A promoted node must connect to the seed's graph (epic/component/codegraph), not merely be semantically near; gate *promotions*, not only external-LLM leads. | med | Breadth without off-topic bleed; closes the circular "ground leads against biased memory" gap. |
| **B6 — negative-signal re-anchor** | *new* | Accept an `exclude-domain` / user-rejection input ("not related to zip import at all") that prunes the bled cluster and re-runs the focus. | med | One human correction re-aims the whole loop instead of restarting the gather. |

**Implementation status (2026-09-04): B0–B6 all implemented + unit-tested (working tree; not yet deployed).**
- **B0** — `common/interrogate/pack.py::load_pack` filters loaded notes by `note.run_id == context_id` (+ a run-scoped `pack.graph`); fixes both `refine` and `define` (shared loader).
- **B1** — a structural-climb tier in the shared `explore/expand.py::expansion_round`: a thin seed promotes its `parent` (captured in `SeedProbe`) *before* G0 and **suppresses** G0 memory recall when it climbed.
- **B2** — `explore/loop.py`: a codegraph note's synopsis tokens are prepended to *every* round's focus (always on); round-0 auto-resolves one dev-panel repo behind `KGA_EXPLORE_CODEGRAPH` (default off).
- **B3** — `explore/loop.py`: a frozen `seed_ref` (seed terms + round-0 neighborhood); a round whose focus shares `< KGA_EXPLORE_MIN_COHERENCE` (default 1) tokens with it stops as "off-seed drift".
- **B4** — `explore/index.py::rank_promotions` (used by `memory_self_seed`): IDF-rarity rank + hub-token suppression (`df/N > 0.4`, only once the index is `>= 20` nodes).
- **B5** — `explore/index.py::graph_grounded` gates round-≥1 promotions on a structural edge to the frozen round-0 seed graph; behind `KGA_EXPLORE_GROUND_PROMOTIONS` (default off).
- **B6** — a new `exclude` phrase (`gather_knowledge(exclude=…)` → `parse_input` → the loop) prunes matching nodes from the pack and steers the focus away; persisted so one correction re-anchors on resume.

All new loop state (`anchor`, `carry`, `ref`, `anchor_ids`, `exclude`) is persisted to GCS by `context_id` (resume-safe).

**Constraints (carry over from §4):** one LLM call per round (thread-offloaded); persist loop state to GCS by
`context_id`; everything cited; human owns the gate; every tier bounded and degrading to a declared gap. Note
that B2's codegraph build now works **server-side** (the agent container now carries Bitbucket creds), but still
needs a **fresh** context — passing `repo=` on an already-complete `context_id` short-circuits the build and
returns 0 nodes.

---

## 8. Extension — the live GCP estate (tiers 5/6/7)

The three source tiers above are all **document** sources — they answer *what the system is meant to do*.
A companion plan adds three **operational** tiers that answer *what is actually deployed and running*, so the
pack exercises the real failure modes, not only the designed ones. They are the operational peers of tiers
1–4 and feed the **same** hypothesize → ground → promote → crawl loop; only the source changes.

> **Full design + diagram:**
> [`../../test-agent-v2/docs/PLAN-gcp-service-exploration-tiers.md`](../../test-agent-v2/docs/PLAN-gcp-service-exploration-tiers.md)
> · [`gcp-service-exploration-tiers.excalidraw`](../../test-agent-v2/docs/gcp-service-exploration-tiers.excalidraw)
> · [`.png`](../../test-agent-v2/docs/gcp-service-exploration-tiers.png)

| Tier | Does | Rides which existing seam |
|---|---|---|
| **5 · DISCOVER** | Enumerate the *prominent* services across every env (`dev`, `dev-staging`, `performance`, `test`, `prod`) for **GKE**, **Cloud Run**, **managed** (Cloud SQL / Pub/Sub) via Cloud Asset Inventory; rank by term-match ∪ liveness ∪ env → promote top-N. | new **seed producer** in `expansion_round` → `gcpsvc:<env>/<platform>/<name>` ids |
| **6 · LOGS** | For each service, read Cloud Logging over an **expanding window** 7 → 14 → 21 → 28 d, widening only until *enough* signal (marginal-yield on time); distill purpose · error-sigs · deps; **redact** secrets/PII. | new **`NodeFetcher(kind="gcpsvc")`** — the "fetch" seam |
| **7 · RELATE** | Infer service-to-service communication edges from log fields · config · Cloud Trace; emit them as `LinkRecord`s so the crawl **walks the service graph**. | in-scope `LinkRecord` + `gcpsvc` in `_fetchable` — the "follow" seam |

**Why this fits the loop, not fights it.** One GCP-explore **sub-agent** (a single `LlmAgent` of the same
shape as `hypothesize`/`leads`) plans envs, ranks prominence, and distills/labels — it never *invents* a
service or an edge; discovery and edges come only from real GCP fields (the **grounding gate**, ported from
tier 3b). The reach is read-only, offloaded to threads, opt-in (`Scope.explore_gcp`, like `follow_web`), and
bounded by the crawl's existing budget. Candidate service-nodes pass through the **same ③ GROUND gate** as
every other tier before promotion — which is exactly what the new band in the diagram shows.

---
*Companion to the agentic-QA enhancement report. The deterministic crawl is the executor; this report adds the
self-exploring shell around it. Diagrams authored in Excalidraw; regenerate the PNGs with the repo's
`render_excalidraw.py`.*
