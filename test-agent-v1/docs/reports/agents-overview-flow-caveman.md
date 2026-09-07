# agents-overview-flow.excalidraw — Caveman Explain

**Big idea: whole hunt in ONE straight line — crawl → interrogate → [evaluate] →
plan → implement. Three robot, one BOSS (Claude), one context_id thread the
whole run. Below them: shared cave with TWO-floor brain.** 🦣➡️🤖

---

## Top: who drive the hunt 👑

- **User** 🧍 — throw first rock: `"test LUZ-123"`.
- **Claude — MCP client & orchestrator** 👑 — the BOSS. Own **every confirm gate** (ask you Yes/No before each ◆ stage), reuse **ONE context_id** for every call. 🧵

---

## Middle: three robot pen (left → right) 🏘️

**① knowledge-gathering · Step 1–2 KNOWLEDGE** 🔍 (blue pen)
`gather_knowledge` (crawl Jira / Confluence + repo, read-only) → `refine` (interrogate + confirm understanding) → `approve` (lock insight pack). 🔒

**② test-evaluation · Step 5 EVALUATION (optional)** ⚖️ (green dashed pen — can skip)
`evaluate_pack` → score the pack. Optional gate, just grade.

**③ test-plan-definition · Step 3–4 TEST PLAN** 🗺️ (purple pen)
`define_plan` (interrogate methodology / scope / metrics) → `approve_plan` (lock the plan) → `implement_plan` (gen test data / scenarios / steps) → `get_scenarios` (read the results).

Each **◆ orange diamond** = BOSS ask you Yes/No before calling that tool. 🚪

---

## Bottom: shared cave — now TWO-floor (CQRS: record + recall) 🗄️🆕

Both robot read/write here. Three rock:

- 🟢 **GCS memory bank · RECORD (write truth)** 📖
  notes · index · runs · graphify. Insight pack live here. 🆕 **→ ② project (async)** side-job feed the recall floor.
- 🔵 **Cloud SQL (Postgres) · SAME instance** 📋⚡
  A2A **task store** + 🆕 **pgvector RECALL** (`memory_node` / `memory_edge`). Durable across revision. One box, two job.
- 🟣 **Vertex AI · claude-sonnet-5** 🧠 *(model refresh — was "Claude Sonnet")*
  distill · plan · scenarios · steps. (Embed brain = `multilingual-embedding-002`.)

---

## 🆕 The new footer rock — Two-Tier Agent Memory (CQRS)

**Status: M0 / M1 / M2 BUILT (working-tree · undeployed) · M3–M6 pending.** 🏗️

- **WRITE:** notes/insights → GCS (truth, unchanged) → **② project (async, off request path)** → Cloud SQL + pgvector recall (reuse the task-store instance).
- brain rows: `memory_node` (vector 768 + tsvector + tags · `content_uri`→GCS) · `memory_edge` (replace `knowledge-index.json`).
- **READ (flag switch):** `retrieve` facade · `MEMORY_BACKEND = gcs → hybrid → postgres`. Default `gcs` = same as today. `hybrid` = vector ∪ text ∪ SQL, then **B4 hub-penalty + B5 grounding** keep bad-bias out.
- **SAFETY:** GCS stay truth → Postgres die ⇒ recall fall back to GCS graph, **hunt never break**. Embed by Vertex `text-multilingual-embedding-002` in the drain.

---

## Rock color meaning 🎨

- 🟧 **orange ellipse** = User
- 🔵 **big blue bar** = Claude boss
- 🔵 **blue pen** = knowledge-gathering robot · 🟩 **green node** = approve/lock
- 🟩 **green dashed pen** = test-evaluation (optional)
- 🟣 **purple pen** = test-plan robot
- 🟢🔵🟣 **three bottom box** = shared cave (record · recall · brain)
- 🟩 **mint footer** = two-tier memory detail (new)

---

## One grunt takeaway

**One line, one boss, one context_id: crawl → interrogate → [grade] → plan → implement.**
Boss ask you Yes/No ◆ at every stage. Robot lean on shared cave.
🆕 **Cave got smart: GCS truth-book + pgvector meaning-brain, on the SAME Cloud SQL box, switch-flag + safe fall-back. Built M0–M2, not deployed. Model now claude-sonnet-5.** 🧠👍

*(Sibling rock: `agents-swimlane-detail` = who-talk-who in order · `agents-software-architecture` = the code box · this rock = the straight-line flow.)*
