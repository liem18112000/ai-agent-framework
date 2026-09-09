# agents-software-architecture.excalidraw — Caveman Explain

**Big idea: three robot still SAME skeleton, but now robot are pure ADK — each is a
`root_agent` served by `to_a2a(root_agent)`, A2A-only. No MCP door inside robot no more.
One `common` engine hold them up. ONE image → FOUR Cloud Run service: 1 gateway boss + 3 A2A robot.** 🦣🧱🤖

---

## Top: the three robot, each same bone 🦴 (now ADK-native)

**① knowledge_gathering · KGA (read-only crawler)** 🔍 (blue)
- `root_agent (ADK)` = `agent.py` · gather · refine (router) · `main:app` = `to_a2a(root_agent)` (A2A + /livez)
- `executor/` = base · common · gather · refine (A2A dispatch) · `loop/` = crawl engine (seed → fetch/{jira·confluence·bitbucket·codegraph}) · `models/`

**② test_plan_definition · TPD (planner)** 🗺️ (purple)
- same `root_agent (ADK)` · `main:app` = `to_a2a(root_agent)`
- `executor/` · `define/` (interrogate engine) · `implement/` (generation engine) · `llm/` · `memory/` · `render/ + models/`

**③ test_evaluation · TEV (scorer)** ⚖️ (cyan)
- `root_agent (ADK) · main:app` = `to_a2a(root_agent)` · `executor/` one-shot · `engine.py` scoring · `metrics/ · golden/ · models.py`

**Middle rock: `X never import`** ❌ — the two big robot must NEVER import each other (red diamond). Still true.

---

## Middle floor: `common` — the shared engine 🧱 (one-way: never import an agent)

Many small brick: `card` · `bridge` (a2a_client · asgi · session) · `interrogate` · `atlassian` · `extract` · 🆕 **`llm` (distill · ModelProvider (VertexClaude))** · `memory` (bank · pg store · retrieve) · 🆕 **`session` (ADK DatabaseSessionService · Cloud SQL)** · `monitoring` · `ops` · `executor` · 🆕 **`middlewares` (GATEWAY + A2A bearer)** · `models` · `codegraph`.

🆕 **What changed:** model access now go through **`ModelProvider`** — one impl only, **`VertexClaudeProvider`** (Gemini backend GONE). The old `taskstore` brick become **`session` = ADK `DatabaseSessionService`** on Cloud SQL (replace the a2a DatabaseTaskStore). Two bearer now: gateway bearer + A2A bearer.

---

## Bottom floor: Runtime — ONE image (kga-v2) → FOUR Cloud Run service 📦☁️

Big change here. No more 3 MCP door · no more bridge sidecar. Now:

- 🔷 **`mcp-gateway-v2`** — the ONE MCP door (`/mcp :8080`, `GATEWAY_BEARER_TOKEN`). Claude connect HERE. Gateway **route each tool → A2A**.
- Three **A2A-only single-container** robot below: `knowledge-gathering-agent-v2` · `test-plan-definition-agent-v2` · `test-evaluation-agent-v2`. Each = `uvicorn main:app :8080` = `to_a2a(root_agent)`, guard by shared `A2A_BEARER_TOKEN`, pick job by `AGENT=kga|tpd|tev` env.
- All FOUR run as ONE **`kga-v2-runtime`** SA. Only the gateway internet-face; robot reach only over A2A.

Three backing rock:
- 🟢 **GCS · `<project>-kga-v2-memory` · RECORD (write truth)** 📖
- 🔵 **Cloud SQL · `kga-v2-taskstore` · `DatabaseSessionService` + pgvector recall** 📋⚡ *(one box, two job)*
- 🟣 **Vertex AI · `VertexClaudeProvider` · `claude-sonnet-5`** 🧠

---

## The footer rock — Two-Tier Agent Memory (CQRS)

Same brain design (v2 doc set). **WRITE:** notes/insights → GCS (truth) → ② project (async, off request path) → Cloud SQL + pgvector recall (shared `common/db.py` engine). **READ (flag):** `common/memory/retrieve.py` · `MEMORY_BACKEND = gcs → hybrid → postgres`; `hybrid` = vector ∪ text ∪ SQL, then **B4 + B5** keep bias out. **SAFETY:** GCS stay truth → Postgres die ⇒ fall back to GCS graph, hunt never break.

---

## Rock color meaning 🎨

- 🔵 **blue pen** = KGA robot · 🟣 **purple pen** = TPD robot · 🩵 **cyan pen** = TEV robot
- 🔴 **red diamond** = "X never import" (robot no import robot)
- 🔵 **blue bar row** = `common` shared engine brick
- 🟢 **green pen** = Runtime (Cloud Run) · 🔷 **solid blue box** = `mcp-gateway-v2` (the ONE MCP door)
- 🟢🔵🟣 **three bottom box** = backing cave (record · recall · brain)
- 🟩 **mint footer** = two-tier memory detail

---

## One grunt takeaway

**Three robot, same skeleton, all pure ADK (`to_a2a(root_agent)`), one `common` engine, ONE image, FOUR service.**
The bridge sidecar GONE — now ONE `mcp-gateway-v2` is the single MCP door and route to 3 A2A-only robot.
Model via `ModelProvider` → `VertexClaudeProvider` (`claude-sonnet-5`, no Gemini); session/task on ADK `DatabaseSessionService` = Cloud SQL `kga-v2-taskstore`. 🚪🧠👍

*(Sibling rock: `agents-overview-flow` = the straight-line flow · `DESIGN-mcp-gateway-target` = the gateway topology · this rock = the CODE boxes.)*
