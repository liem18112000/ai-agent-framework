# agents-swimlane-detail.excalidraw — Caveman Explain

**Big idea: who shout to who, IN ORDER. Human never touch robot direct. Human
talk to BOSS robot (Claude). Boss knock on each robot door (bridge), door-guard
whisper to real robot inside (A2A). All robot dig same shared cave.** 🦣📣🤖

---

## The seven standing pole (lanes, left → right) 🪵

1. **User** 🧍 — you. Throw first rock, answer question, get final plan.
2. **Claude (MCP client)** 👑 — BOSS robot. Hold talking-stick. Drive every loop, ask every Yes/No.
3. **KGA door-guard** 🛡️ — `KGA bridge (MCP↔A2A)`. Take boss knock (MCP), turn into inside-whisper (A2A).
4. **KGA robot** 🔍 — `knowledge-gathering agent (A2A)`. The gatherer.
5. **TPD door-guard** 🛡️ — `TPD bridge (MCP↔A2A)`. Same guard trick for plan robot.
6. **TPD robot** 🗺️ — `test-plan-definition agent (A2A)`. The planner.
7. **Shared cave** 🗄️ — `GCS · pgvector · SQL · Vertex`. Where all robot keep stuff + brain.

---

## Rule of the arrow 🏹

- **solid arrow →** = "me ASK you do thing" (tool call / request).
- **dashed arrow ⇢** = "here your answer BACK" (reply / return).
- **◆ diamond** = BOSS ask human **Yes/No FIRST** before doing. Human hold the gate. 🚪
- **loop rock** = boss + human go round-and-round, turn by turn, till done. 🔁

---

## The hunt, band by band (top → bottom) 🏞️

**① GATHER** 🔍
Human grunt **"test LUZ-158390"** → boss call `gather_knowledge(seed, depth, repo)` →
door-guard whisper KGA robot (`A2A message/send` + **bearer token**). Robot **crawl
Jira/Confluence + repo code-graph, distill** → write to cave: **notes → GCS**, **task → Cloud SQL**.
🆕 **also fire ② project (async) → pgvector recall brain · M2** (quiet, side job, not slow boss).
Robot hand back **context_id + crawl summary**. ⇢

**② REFINE** ❓
Boss show summary, ask **◆ "refine now? Yes/No"**. Human say **Yes**, answer each question round →
`refine(context_id[, answer])` through door → robot shoot back question round (`state: input-required`).
**LOOP: business → technical → QA** until **'Refinement complete'**. 🔁

**③ APPROVE** ✅
Same context_id. **◆ approve** → robot **assemble understanding + Q/A** → **insight pack LOCKED → GCS**. 🔒

**④ EVALUATE** ⚖️ *(optional gate — can skip)*
**◆ evaluate_pack(context_id)** → wake **test-evaluation robot** (bridge → agent) → it **read pack (GCS)** →
give **Pack Quality Score**. Just LOOK, **never block** hunt. 👀

**⑤ DEFINE** 🗺️
Boss call `define_plan(context_id)` → whisper TPD robot (`A2A` + bearer) → robot **read pack (GCS) · interrogate** →
question round (**methodology / scope / metrics**). **LOOP with human** until **'Plan definition complete'**. 🔁

**⑥ IMPLEMENT** 🧱
**◆ approve_plan** → **plan LOCKED (GCS)** → **◆ implement_plan** → TPD robot
**gen test data / scenarios / steps (Vertex claude-sonnet-5) → GCS** → hand human the
**final test plan + scenarios + steps**. 🎉

---

## 🆕 The BIG new rock — shared cave got TWO-TIER brain (bottom green box) 🧠

Before, cave was one flat book. Now cave have **two floor (CQRS)**:

- 📖 **GCS = truth book (WRITE floor).** notes/insights → GCS. Never lie, never change. STILL the boss of truth.
- ⚡ **Cloud SQL + pgvector = fast RECALL brain (READ floor).** `memory_node` (number-vector 768 + text-search + tags),
  `memory_edge` (take over old `knowledge-index.json`). Find by **MEANING**, not just same-word.
- 🔀 **Read go through `retrieve` facade, flag `MEMORY_BACKEND = gcs → hybrid → postgres`.**
  Default `gcs` = same as today. `hybrid` = vector ∪ text ∪ SQL, then **B4 hub-penalty + B5 grounding** keep bad-bias out.
- 🛡️ **Postgres die? → fall back to GCS book. Hunt NEVER break.** Project job side-job (best-effort). Embed by Vertex `text-multilingual-embedding-002` in the drain.
- 🏗️ **Status: M0 / M1 / M2 BUILT** (working-tree, **not deployed yet**). M3–M6 (embeddings, hybrid SQL, backfill, terraform) **still to do.**

---

## Rock color meaning 🎨

- 🟧 **orange pole** = User (human)
- 🟦 **blue pole** = Claude boss + KGA robot
- ⬜ **grey pole** = the two door-guard (bridge)
- 🟪 **purple pole** = TPD robot
- 🟩 **green pole + green box** = shared cave / locked-pack / two-tier memory
- 🟦 **blue solid arrow** = tool call · **grey dashed** = reply · **green arrow** = write-to-cave
- 🟨 **amber box** = a loop note
- 🩵 **cyan dashed box** = test-evaluation robot (optional)

---

## One grunt takeaway

**Human → BOSS → door-guard → robot → cave, and back. Always in order.**
Boss hold every Yes/No gate ◆ and drive every loop 🔁 with human.
Robot-① gather + write cave; robot-② plan + gen; robot-eval just grade (no block).
🆕 **Cave now smart: truth-book (GCS) + meaning-brain (pgvector), switch-flag, safe fall-back.
Built M0–M2, not deployed.** Robot remember better now. 🧠👍

*(Sibling rock: `full-flow.excalidraw` = the whole loop; `deployment-architecture.excalidraw` = where robot LIVE; this rock = who-talk-who IN ORDER.)*
