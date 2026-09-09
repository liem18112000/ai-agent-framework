# self-exploring-knowledge-gather.excalidraw — Caveman Explain

**Big idea: don't STOP at the seed. Robot start from a thin/blank ticket, GUESS what it
might touch, fan out across three source ladders (cheapest+most-trusted first), keep
only what it can CITE, then crawl. External LLM only points the way — it is NOT a
source of truth.** 🧭🐾

**(v2 doc set — same self-exploration loop as v1; names kept current.)**

---

## The PRINCIPLE rock (grey, left)

The **deterministic frontier crawl stays the EXECUTOR** (unchanged). An agentic shell
just feeds it seeds from a **3-tier source ladder**, cheapest + most-trusted first.
**Every fact cited · nothing ungrounded · human prunes.** 🪨

---

## The loop, step by step

- **THIN / BLANK SEED** 🔴 — title · labels · component, no links. The hard case.
- **① HYPOTHESIZE (1 LLM call)** 🟪 — guess subsystems / entities / prior tickets.
- **② EXPAND → concrete queries per tier** 🔵 — turn guesses into real search strings.

Then fan out to **three source tiers** (four boxes):
- **TIER 1 · MEMORY** 🟢 — `search_memory(terms)`, GCS index + prior insights.
  *verified · free.*
- **TIER 2 · ATLASSIAN** 🔵 — `JQL(title) · CQL(title)` — SEARCH, not just follow links.
  *authoritative · cheap.*
- **TIER 3a · WEB** 🟠 — WebSearch → fetch → distill (external-web fetchable).
  *verifiable · cited.*
- **TIER 3b · EXTERNAL LLM** 🟠 — enumerate leads / terms, **NOT facts**.
  *unverified · breadth.*

- **③ GROUND — the grounding gate** ⬜ — keep a candidate IFF it resolves to a fetchable,
  citable source (jira / confluence / web / code). **Triangulate ≥ 2 sources ⇒ high
  confidence.** LLM leads ground here or are DROPPED. 🛡️
- **④ PROMOTE** 🟪 — survivors → canonical seeds.
- **⑤ CRAWL** 🟢 — `loop/crawl.py`, the deterministic executor (unchanged).
- **⑥ REFLECT** ⬜ — new in-scope nodes? write reflection + provenance → memory.
- **CONVERGE** 🔵 — → pack (+ declared gaps) → **refine (HUMAN gate, unchanged).**

**Two loop-backs:** the big right arrow = **loop until converged (refined hypotheses)**
back to HYPOTHESIZE; the dashed-red arrow = **leads recycle → new queries (not facts)**
back to EXPAND. 🔁

---

## Rock color meaning 🎨

- 🔴 **red** = the thin/blank seed (the hard start)
- 🟪 **purple** = LLM-shaped step (hypothesize · promote)
- 🔵 **blue** = expand / atlassian tier / converge
- 🟢 **green** = trusted+free (memory tier · deterministic crawl)
- 🟠 **orange** = external tiers (web = cited · external LLM = breadth-only)
- ⬜ **grey** = the PRINCIPLE, the grounding gate, and reflect
- 🔴 **dashed red** = leads recycle into new queries (leads, never facts)

---

## One grunt takeaway

**Thin seed? Guess → fan out 3 tiers (memory → Atlassian → web/LLM) → keep only what you
can CITE → triangulate ≥2 → promote → crawl → reflect → loop till converged.**
Deterministic crawl still the executor; LLM only a lead-scout, never truth; human still
the last gate. Robot stop dead-ending on empty tickets. 🧭👍

*(Sibling rocks: `self-explore-memory-bias` = the drift a thin seed can cause here;
`self-learning-memory-loop` = how each reflection becomes durable memory.)*
