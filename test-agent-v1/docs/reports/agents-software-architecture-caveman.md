# agents-software-architecture.excalidraw — Caveman Explain

**Big idea: three robot are SAME skeleton. They all stand on ONE shared engine
(`common`), and all ride in ONE image as three Cloud Run service. Robot never
import robot; robot only import `common`. One-way rule.** 🦣🧱🤖

---

## Top: the three robot, each same bone 🦴

**① knowledge_gathering · KGA (read-only crawler)** 🔍 (blue)
- `bridge/` = `mcp_server.py` (MCP door, client-side) · `server.py` = A2A app + `/livez /readyz`
- `executor/` = base · common · gather · refine (A2A dispatch + handlers)
- `loop/` = crawl engine: seed → fetch/{ jira · confluence · bitbucket · codegraph } → crawl
- `models/` = crawl

**② test_plan_definition · TPD (planner)** 🗺️ (purple)
- same `bridge/` + `server.py`
- `executor/` = base · common · define · implement
- `define/` = interrogate engine (decision · loop · plan · questions)
- `implement/` = generation engine (generate · scenarios · steps · testdata)
- `llm/` · `memory/` (render · template · writers) · `render/ + models/` (gherkin · pack · plan · scenario)

**③ test_evaluation · TEV (scorer)** ⚖️ (cyan)
- `bridge/` + `server.py` · `executor/` = one-shot evaluate_pack
- `engine.py` = scoring (evaluate_pack → EvalReport, deterministic)
- `metrics/` · `golden/` · `models.py` = trajectory · node_overlap · entities · ragas_judge · pqs · rubrics …

**Middle rock: `X never import`** ❌ — the two big robot must NEVER import each other. (red diamond between them.)

---

## Middle floor: `common` — the shared engine 🧱 (one-way: never import an agent)

Many small brick: `card` · `bridge` (a2a_client · asgi · session · prompts) · `interrogate` · `atlassian` (read-only client) · `extract` · `llm` · 🆕 **`memory` (bank · render · pg store · retrieve)** · 🆕 **`taskstore` (Cloud SQL/mem · shared `db.py` engine)** · `monitoring` · `ops` · `executor` · `middlewares` · `models` · `codegraph`.

🆕 **What changed:** the `memory` brick now also hold the **pg store** (`common/memory/pg/*`) + the **`retrieve` facade** (`common/memory/retrieve.py`); `taskstore` now share ONE async engine from the new **`common/db.py`** (task store + memory sit on the same Cloud SQL pool).

---

## Bottom floor: Runtime — one image → THREE Cloud Run service 📦☁️

Each service = **bridge (ingress :8080, Claude → /mcp)  →  agent (sidecar :8081, private, localhost only)**. Agent NEVER internet-face; bridge pin the instance (session_affinity + min=max=1), all run as ONE `kga-runtime` SA.

Three backing rock (now two-floor brain):
- 🟢 **GCS memory bank · RECORD (write truth)** 📖
- 🔵 **Cloud SQL · task store + pgvector recall** 📋⚡ *(same box now do BOTH job)*
- 🟣 **Vertex AI · claude-sonnet-5** 🧠 *(model refresh — was "Claude Sonnet")*

---

## 🆕 The new footer rock — Two-Tier Agent Memory (CQRS)

**Status: M0 / M1 / M2 BUILT (working-tree · undeployed) · M3–M6 pending.** 🏗️

- **WRITE:** notes/insights → GCS (truth) → **② project (async, off request path)** → Cloud SQL + pgvector recall (reuse task-store instance / shared `common/db.py` engine).
- brain: `memory_node` (vector 768 + tsvector + tags · `content_uri`→GCS) · `memory_edge` (replace `knowledge-index.json`) — code lives in `common/memory/pg/*`.
- **READ (flag switch):** `common/memory/retrieve.py` facade · `MEMORY_BACKEND = gcs → hybrid → postgres`. Default `gcs` = same as today; `hybrid` = vector ∪ text ∪ SQL then **B4 + B5** keep bias out.
- **SAFETY:** GCS stay truth → Postgres die ⇒ fall back to GCS graph, hunt never break. Embed = Vertex `text-multilingual-embedding-002`, in the drain.

---

## Rock color meaning 🎨

- 🔵 **blue pen** = KGA robot · 🟣 **purple pen** = TPD robot · 🩵 **cyan pen** = TEV robot
- 🔴 **red diamond** = "X never import" (robot no import robot)
- 🔵 **blue bar row** = `common` shared engine brick
- 🟢 **green pen** = Runtime (Cloud Run services)
- 🟢🔵🟣 **three bottom box** = backing cave (record · recall · brain)
- 🟩 **mint footer** = two-tier memory detail (new)

---

## One grunt takeaway

**Three robot, same skeleton, one `common` engine, one image, three Cloud Run service.
Robot import `common` only — never each other.** Bridge face world, agent hide inside.
🆕 **`common/memory` now two-floor: `pg store` + `retrieve` facade + shared `common/db.py` engine; backing Cloud SQL box does task-store AND pgvector recall; model now claude-sonnet-5. Built M0–M2, not deployed.** 🧠👍

*(Sibling rock: `agents-overview-flow` = straight-line flow · `agents-swimlane-detail` = who-talk-who in order · `deployment-architecture` = the GCP boxes · this rock = the CODE boxes.)*
