# self-learning-memory-loop.excalidraw — Caveman Explain

**Big idea: robot LEARN after each hunt step. Robot scratch the good lesson into
the shared cave-wall (GCS), quiet-quiet on the side (not slow the hunt), with a
GUARD so no bad lesson poison future hunt. Next hunt start smarter. Loop close.**
🦣🧠🔁

**Status: robot already DO this — BUILT & DEPLOYED, proven live 2026-09-04, switch = ON.** ✅

---

## ① SIGNALS — every step drop a clue 🐾 (blue boxes)

After each pipeline step the robot notice something worth keeping (cheap, no big-brain call):
- **gather** → "seed live in repo axonivy-prod/luz_finance" (codegraph fact) 🔍
- **refine** → human OVERRODE robot → that a **correction** (strongest clue) ✋
- **define** → scope fix / plan contradiction 🗺️
- **implement** → one short "N scenarios: X happy, Y angry" coverage note 🧱

---

## ② CAPTURE — write it down, but on the SIDE ⚙️ (async, off the hunt path)

Robot NOT stop the hunt to write. It drop a tiny job and keep going:

1. **enqueue CaptureJob (O(1))** → handler return **right now**. ⚡
2. **GCS queue** (`memory/learn/capture-queue.json`, mutate_json CAS) holds the job. 📥
3. **drain** at head of NEXT request pulls the job (off the first hunt's path). 🚰
4. **distil** — ONE bounded big-brain call → statement + citations + confidence + kind. 🧪
5. **GATE** — the guard: **grounding (B5)** (no citation → no lesson) · **dedup** (content-key + supersede) · **confidence tier**. 🛡️
6. **persist** — `upsert_insight` → cave-wall: GCS note + index node + edges to the citations. 🪨

*(Why side-job? Cloud Run choke robot CPU after it answer; serial big-brain call once tripped ERROR_TIMEOUT. So distil live in the drain, NEVER the handler.)*

---

## The cave-wall 📖 (green box)

**Shared GCS agent memory** — Insight nodes, `kind = lesson · correction · gotcha`, plus edges to the citation rocks. G0 self-seed / `search-memory` already read these node → recall for free.

---

## ③ RECALL — next hunt read the old lesson 🔁 (teal boxes)

- **recall_lessons** — pull lesson whose **citation ∩ this run's seed** (B5 structural, NOT word-match). 🎯
- **Pack.lessons** — put them in the "Prior lessons" preamble → feed refine / define.
- **Loop-back arrow wraps the whole left side → into the NEXT run's `gather`.** Robot reminded BEFORE it repeat a mistake. 🧠
- 🆕 **L7 (planned, dashed box):** semantic recall via **two-tier pgvector M4** (vector ∪ text ∪ SQL, B4/B5) → find lesson by MEANING, so a lesson from a *different* ticket still surface. Today recall is structural-only.

**Governance rock (right):** `veto-lesson` → mark vetoed + **drop the index node** (gone from ALL recall). `search-lessons` → look at what robot learned.

---

## ⚠️ SAFETY — this the memory-bias trap AGAIN (orange band)

Auto-write to shared cave IS the exact failure the B0–B6 de-bias just fixed → de-bias matter MORE, not less:
- **cited** (no grounding → no lesson) · **confidence tiers** (human = high, agent = low, never auto-shared) ·
- **human veto is boss** · **B4 hub-penalty + B5 grounding on recall** ·
- **default context-scoped** (promote to shared only on human-confirm / ≥N runs agree) · **supersede on contradiction**.

*(Storage note: queue live on the memory bank's own GCS (mutate_json CAS), NOT the A2A Cloud SQL task store. And a "lesson" is NOT new plumbing — reuse the Insight rock.)*

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

**Robot notice → drop tiny job → later drain distils → GUARD checks (cited? dup? confident?) →
scratch on cave-wall → next hunt reads it → start smarter.**
All on the SIDE (never slow the hunt), all GATED (bad lesson can't poison future hunt).
🆕 **Recall by-word today; by-MEANING when two-tier pgvector M4 land (L7).** Robot stop re-learning
the same lesson. 🧠👍

*(Sibling rock: two-tier memory (`two-tier-agent-memory-pgvector`) = the RECALL brain this loop leans on; `full-flow` = the whole hunt.)*
