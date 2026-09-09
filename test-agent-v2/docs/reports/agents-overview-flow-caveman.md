# agents-overview-flow.excalidraw — Caveman Explain

**Big idea: whole hunt still ONE straight line — crawl → interrogate → [evaluate] →
plan → implement. But now BOSS (Claude) knock on ONE door only: `mcp-gateway-v2`.
Gateway take tool call, throw it to the right A2A-only robot. One `context_id`
thread the whole run.** 🦣➡️🚪🤖

---

## Top: who drive the hunt 👑

- **User** 🧍 — throw first rock: `"test LUZ-123"`.
- **Claude — MCP client & orchestrator** 👑 — the BOSS. Own **every confirm gate** (ask you Yes/No before each ◆ stage), reuse **ONE context_id** for every call. 🧵 Now talk to **ONE endpoint** only.

## New rock: the ONE door 🚪 (blue bar)

- **`mcp-gateway-v2`** — single MCP endpoint (`/mcp`, `GATEWAY_BEARER_TOKEN`). Claude connect HERE and nowhere else. Gateway **route each tool call → A2A agent** (`A2A_BEARER_TOKEN`). No more three MCP door · no more bridge sidecar. One gateway → three A2A-only robot.

---

## Middle: three robot pen (left → right) 🏘️

**① knowledge-gathering · Step 1–2 KNOWLEDGE** 🔍 (blue pen)
`gather_knowledge` (crawl Jira / Confluence + repo, read-only) → `refine` (interrogate + confirm) → `approve` (lock insight pack). 🔒

**② test-evaluation · Step 5 EVALUATION (optional)** ⚖️ (green dashed pen — can skip)
`evaluate_pack` → score the pack. Read-only gate, just grade.

**③ test-plan-definition · Step 3–4 TEST PLAN** 🗺️ (purple pen)
`define_plan` → `approve_plan` → `implement_plan` (gen test data / scenarios / steps) → `get_scenarios` (read results).

Each **◆ orange diamond** = BOSS ask you Yes/No before calling that tool. 🚪

---

## Bottom: shared cave — CQRS (record + recall) 🗄️

Both robot read/write here. Three rock — all v2 name now:

- 🟢 **GCS · `<project>-kga-v2-memory` · RECORD (write truth)** 📖 notes · index · runs · graphify. Insight pack live here → ② project (async) feed the recall floor.
- 🔵 **Cloud SQL · `kga-v2-taskstore`** 📋⚡ ADK **`DatabaseSessionService`** + pgvector RECALL (`memory_node` / `memory_edge`). Durable across revision. One box, two job.
- 🟣 **Vertex AI · `VertexClaudeProvider`** 🧠 `claude-sonnet-5` — distill · plan · scenarios. Gemini backend GONE. (Embed = `multilingual-embedding-002`.)

---

## Footer rock — Two-Tier Agent Memory (CQRS)

Same brain design as before, now the v2 doc set. **WRITE:** notes/insights → GCS (truth) → ② project (async, off request path) → Cloud SQL + pgvector recall. **READ (flag):** `retrieve` facade · `MEMORY_BACKEND = gcs → hybrid → postgres`; `hybrid` = vector ∪ text ∪ SQL, then **B4 hub-penalty + B5 grounding** keep bias out. **SAFETY:** GCS stay truth → Postgres die ⇒ fall back to GCS graph, hunt never break.

---

## Rock color meaning 🎨

- 🟧 **orange ellipse** = User · 🔵 **light blue bar** = Claude boss
- 🔷 **solid blue bar** = `mcp-gateway-v2` (the ONE MCP door)
- 🔵 **blue pen** = knowledge-gathering · 🟩 **green node** = approve/lock
- 🟩 **green dashed pen** = test-evaluation (optional) · 🟣 **purple pen** = test-plan
- 🟢🔵🟣 **three bottom box** = shared cave (record · recall · brain)
- 🟩 **mint footer** = two-tier memory detail

---

## One grunt takeaway

**One line, one boss, one context_id, and now ONE door.**
Claude knock only on `mcp-gateway-v2`; gateway route each tool → the right A2A-only robot.
Cave got smart: GCS truth-book + pgvector meaning-brain on the SAME Cloud SQL `kga-v2-taskstore` (ADK `DatabaseSessionService`), model via `VertexClaudeProvider` (`claude-sonnet-5`). 🚪🧠👍

*(Sibling rock: `agents-software-architecture` = the CODE boxes · `DESIGN-mcp-gateway-target` = the gateway topology · this rock = the straight-line flow.)*
