# self-learning-memory-loop.excalidraw — Caveman Explain

**Big idea: robot LEARN after each hunt step. Robot scratch the good lesson into the
shared cave-wall (GCS), quiet-quiet on the side (not slow the hunt), with a GUARD so
no bad lesson poison future hunt. Next hunt start smarter. Loop close.** 🦣🧠🔁

**Status: robot already DO this — BUILT & DEPLOYED, live-verified 2026-09-04, flags =1.**
✅ (v2 doc set — the self-learning loop; recall structural-only → semantic = L7 two-tier M4.)

---

## ① SIGNALS — every step drop a clue 🐾 (blue boxes)

After each pipeline step the agent notice something worth keeping (cheap, no big-brain call):
- **gather** → thin-seed / repo / codegraph fact 🔍
- **refine** → human OVERRIDE → that a **correction** (strongest clue) ✋
- **define** → scope correction / contradiction 🗺️
- **implement** → one short coverage lesson (1 bounded) 🧱

*(enqueue CaptureJob O(1) — the handler returns immediately.)*

---

## ② CAPTURE — write it down, but on the SIDE ⚙️ (async · off the response path)

Robot NOT stop the hunt to write. Drop a tiny job and keep going (at-least-once · idempotent):

1. **GCS queue** — `memory/learn/capture-queue.json` (mutate_json CAS) holds the job 📥
2. **drain** at head of the NEXT request pulls it — off the first hunt's path 🚰
3. **distil** — ONE bounded LLM call, thread-offloaded → statement + refs + conf + kind 🧪
4. **GATE** — the guard: **grounding (B5)** · **dedup** (content-key + supersede) ·
   **confidence tier** 🛡️
5. **persist** — `upsert_insight` → cave-wall: GCS note + index node + edges 🪨

*(Why side-job? Cloud Run choke robot CPU after it answer; a serial big-brain call once
tripped ERROR_TIMEOUT. So distil live in the drain, NEVER the handler.)*

---

## The cave-wall 📖 (green box)

**Shared GCS agent memory** — Insight nodes, `kind = lesson · correction · gotcha`, plus
edges to the citation rocks. G0 self-seed / `search-memory` already recall these nodes.

---

## ③ RECALL — next hunt read the old lesson 🔁 (teal boxes)

- **recall_lessons** — B5 structural: pull lesson whose `source_ref ∩ seed_ref` (NOT
  word-match) 🎯
- **Pack.lessons** — put them in the "Prior lessons" preamble → feed refine / define
- **Loop-back arrow wraps the whole left side → into the NEXT run's `gather`.** Robot
  reminded BEFORE it repeat a mistake 🧠
- 🆕 **L7 (planned, dashed box):** semantic recall via **two-tier pgvector M4** (vector ∪
  text ∪ SQL, B4/B5) → find lesson by MEANING, so a lesson from a *different* ticket still
  surface. Today recall is structural-only.

**Governance rocks (right):** `veto-lesson` → mark vetoed + **drop the index node** (gone
from ALL recall) 🔴 · `search-lessons` → inspect what robot learned.

---

## ⚠️ SAFETY — this the memory-bias trap AGAIN (orange band)

Auto-write to shared cave IS the exact failure the B0–B6 de-bias just fixed → de-bias
matter MORE, not less: **cited** (no grounding → no lesson) · **confidence tiers**
(human=high, agent=low, never auto-shared) · **human veto authoritative** · **B4/B5 on
recall** · **default context-scoped** (promote only on human-confirm / ≥N corroboration)
· **supersede on contradiction**.

*(Storage note: queue live on the memory bank's own GCS (mutate_json CAS), NOT the A2A
Cloud SQL task store. A "lesson" is NOT new plumbing — reuse the Insight rock.)*

---

## Rock color meaning 🎨

- 🔵 **blue** = pipeline step (signal source)
- 🟢 **green** = GCS (queue · persist · the cave-wall) · ⬜ **grey** = drain
- 🟣 **purple** = big-brain distil · 🟠 **amber** = the GATE (guard)
- 🩵 **teal** = recall (recall_lessons · Pack.lessons)
- 🟪 **purple dashed** = L7 future (semantic recall)
- 🔴 **red** = veto · 🟧 **orange band** = SAFETY
- 🟩 **green badge** = BUILT & DEPLOYED status

---

## One grunt takeaway

**Robot notice → drop tiny job → later drain distils → GUARD checks (cited? dup?
confident?) → scratch on cave-wall → next hunt reads it → start smarter.**
All on the SIDE (never slow the hunt), all GATED (bad lesson can't poison future hunt).
🆕 **Recall by-word today; by-MEANING when two-tier pgvector M4 land (L7).** Robot stop
re-learning the same lesson. 🧠👍

*(Sibling rocks: `two-tier-agent-memory-pgvector` = the RECALL brain this loop leans on;
`self-explore-memory-bias` = the drift this GUARD stop.)*
