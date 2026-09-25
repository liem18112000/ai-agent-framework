# agents-swimlane-detail.excalidraw — Caveman Explain

**Big idea: who shout to who, IN ORDER — v2 way. Human never touch robot direct.
Human talk to BOSS robot (Claude). Boss knock on ONE door only — the `mcp-gateway-v2`.
That one door pass every knock to the right robot inside (A2A). No more per-robot door!** 🦣📣🚪

---

## The six standing pole (lanes, left → right) 🪵

1. **User** 🧍 — you. Throw first rock, answer question, get final plan.
2. **Claude (MCP client)** 👑 — BOSS robot. Hold talking-stick. Drive every loop, ask every Yes/No.
3. **mcp-gateway-v2** 🚪 — THE ONE DOOR. `MCP :8080 · bearer`. Boss knock here for EVERY tool.
   Door turn boss-knock (MCP) into inside-whisper (A2A) and send to right robot.
4. **KGA agent-v2** 🔍 — `knowledge-gathering · A2A-only`. The gatherer. No door of its own now.
5. **TPD agent-v2** 🗺️ — `test-plan-definition · A2A-only`. The planner. Also no own door.
6. **Shared state** 🗄️ — `GCS · pgvector · CloudSQL · Vertex`. Where all robot keep stuff + brain.

*(v2 smash the door-guards into the ONE gateway.)*

---

## Rule of the arrow 🏹

- **solid arrow →** = "me ASK you do thing" (tool call / request).
- **dashed arrow ⇢** = "here your answer BACK" (reply / return).
- **◆ diamond** = BOSS ask human **Yes/No FIRST** before doing. Human hold the gate. 🚪
- **loop rock** = boss + human go round-and-round, turn by turn, till done. 🔁

---

## The hunt, band by band (top → bottom) 🏞️

**① GATHER** 🔍
Human grunt **"test LUZ-158390"** → boss call `gather_knowledge(seed, depth, repo)` on the **gateway** (MCP) →
gateway whisper KGA robot (`A2A message/send` + **A2A_BEARER**). Robot **crawl Jira/Confluence + repo
codegraph, distill** → write to cave: **notes + codegraph → GCS**, **session → kga-v2-taskstore**.
🆕 side job: **② project (async) → pgvector recall**. Robot hand back **context_id + summary**. ⇢

**② REFINE** ❓
Boss show summary, ask **◆ "refine now? Yes/No"**. Human **Yes**, answer each round →
`refine(context_id[, answer])` **via gateway** → robot shoot back question round (`state: input-required`).
**LOOP: business → technical → QA** until **'Refinement complete'**. 🔁

**③ APPROVE** ✅
Same context_id. **◆ approve** → robot **assemble understanding + Q/A** → **insight pack LOCKED → GCS**. 🔒

**④ EVALUATE** ⚖️ *(optional gate — can skip)*
**◆ evaluate_pack(context_id)** → gateway route to **test-evaluation-v2** robot (`A2A-only · via gateway`) →
it **read pack (GCS)** → give **Pack Quality Score**. Just LOOK, **never block** hunt. 👀

**⑤ DEFINE** 🗺️
Boss call `define_plan(context_id)` on the **gateway** (MCP) → gateway whisper TPD robot (`A2A` + bearer) →
robot **read pack (GCS) · interrogate** → question round (**methodology / scope / metrics**).
**LOOP with human** until **'Plan definition complete'**. 🔁

**⑥ IMPLEMENT** 🧱
**◆ approve_plan** → **plan LOCKED (GCS)** → **◆ implement_plan** → TPD robot
**gen test data / scenarios / steps (Vertex claude-sonnet-5) → GCS** → hand human the
**final test plan + scenarios + steps**. 🎉
🆕 big plan go **Pub/Sub**: TPD **publish batch jobs** (`tpd-gen-batches`) → **push POST · OIDC** →
`tpd-gen-worker` robot **generate scenario → GCS** → TPD **poll result → merge**. Topic dead? TPD just
do it himself (**synchronous fallback**, `TPD_GEN_MODE=workers`). 🔁

**⑦ EXECUTE** 🏃 *(Pillar 2 — now RUN the .feature, not just write it)*
Boss call **◆ `run_suite(context_id, env)`** on the **gateway** (MCP → A2A) → gateway whisper
**test-executor-v2** robot (`A2A-only · via gateway`). Robot open **Run Sandbox** — **Playwright** for
screen, **httpx** for API, **LLM-translate** when plan only word-word. Robot **record env + run →
Postgres** (`exec_environment` · `exec_run`) **+ traces → GCS**. 🗄️
Run is LONG, so robot answer in pieces: **`[state: in_progress]` → boss re-poll → `[done]`** — then
**real signal** go to **test-evaluation-v2** (`evaluate_plan`). ⇢
Step break? Robot **triage: Bug / Heal / Flaky / Env**, and **◆ self-heal only behind a Yes/No gate —
NEVER silent**. Bounded loop: **run → measure → (heal) → triage**. 🩹

---

## The shared cave — TWO-TIER brain, now DEPLOYED (bottom green box) 🧠

- 📖 **GCS = truth book (WRITE floor).** notes/insights → GCS. Never lie, never change.
- ⚡ **Cloud SQL + pgvector = fast RECALL brain (READ floor).** `memory_node` (vector 768 + text-search + tags),
  `memory_edge` (took over old `knowledge-index.json`). Find by **MEANING**, not just same-word.
- 🔀 **Read through `retrieve` facade, flag `MEMORY_BACKEND = gcs → hybrid → postgres`.** hybrid = vector ∪ text ∪ SQL,
  then **B4 hub-penalty + B5 grounding** keep bad-bias out.
- 🛡️ **Postgres die → fall back to GCS book. Hunt NEVER break.** Embed by Vertex in the drain.
- 🏗️ **Status: M0–M6 BUILT · LIVE on klara-nonprod (hybrid · europe-west6).** No longer just working-tree. ✅

---

## Rock color meaning 🎨

- 🟧 **orange pole** = User (human)
- 🟦 **light-blue pole** = Claude boss + KGA agent-v2
- 🟦 **strong-blue pole** = the ONE `mcp-gateway-v2` (the single door)
- 🟪 **purple pole** = TPD agent-v2
- 🟩 **green pole + green box** = shared cave / locked-pack / two-tier memory
- 🟦 **blue solid arrow** = tool call · **grey dashed** = reply · **green arrow** = write-to-cave
- 🟨 **amber box** = a loop note
- 🩵 **cyan dashed box** = test-evaluation-v2 robot (optional)
- 🟠 **orange dashed box + orange band** = test-executor-v2 robot + the EXECUTE band (Pillar 2)
  — orange here mean *the band*, NOT the User pole; arrow inside still follow normal blue/grey/green rule

---

## One grunt takeaway

**Human → BOSS → ONE gateway → robot → cave, and back. Always in order.**
Big v2 change: no more per-robot door. Boss knock ONE `mcp-gateway-v2` for every tool;
gateway route (A2A + bearer) to the right A2A-only robot.
Boss still hold every Yes/No gate ◆ and drive every loop 🔁 with human.
Cave smart: truth-book (GCS) + meaning-brain (pgvector) — now **LIVE**, not just built. 🧠👍
🆕 And hunt no stop at *writing* the test — band ⑦ **RUN** it for real (test-executor-v2) and bring
back real signal. Write-test → run-test → judge-test, all one line. 🏃🩹

*(Sibling rock: `full-flow.excalidraw` = whole loop; `deployment-architecture.excalidraw` = where robot LIVE;
`DESIGN-mcp-gateway-target.*` = the one-door blueprint; this rock = who-talk-who IN ORDER.)*
