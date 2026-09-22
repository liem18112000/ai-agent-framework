# adk-vs-current-stack.excalidraw — Caveman Explain

**Big idea: old rock ask "should we take ADK tool?" — v2 rock say "WE ALREADY TOOK IT."
Whole stack now ADK-native. Robot served by `to_a2a`, model come through ONE door
`ModelProvider(VertexClaude)`, and ONE `mcp-gateway-v2` front all three robot. Gemini gone.** 🦣🔧✅

---

## ① Top row — the v2 pipeline at a glance 👀

Claude Code → **mcp-gateway-v2** (`MCP :8080 · one endpoint`) → **A2A-only agents** (`KGA / TPD / TEV · to_a2a`)
→ **Deterministic pipeline** (`ADK Runner`) → **GCS kga-v2-memory + Cloud SQL sessions**.
One knock-door, three robot behind it.

---

## The two-column story — BEFORE vs NOW 🪨🪨

**Left = v1 · WHAT WE HAD** (a2a-sdk-direct) 🕰️
Python drove every step. Each robot had its OWN MCP bridge sidecar (client-side, one per service).
Claude Sonnet 5 called DIRECT. Runtime = Cloud Run · Cloud SQL `DatabaseTaskStore` · GCS bank. All true — but OLD.

**Right = v2 · WHAT WE ADOPTED** (ADK-native) ✅
- ① The agent **LOOP** is now REAL — `LlmAgent` for KGA explore · TPD implement gens · TEV judge. ADK Runner + **DatabaseSessionService**.
- ② **ADK-native serving** — every robot = `to_a2a(root_agent)`; ONE `mcp-gateway-v2` front all three.
- ③ Claude via **ModelProvider** — `VertexClaudeProvider` sole impl. `claude-sonnet-5` on Vertex. **No LiteLLM, no Gemini.**
- ④ Runtime — Cloud Run · Cloud SQL `kga-v2-taskstore` · GCS `kga-v2-memory`. Own store, own bucket, SA `kga-v2-runtime`.

*(In v1 the ② amber box and ③ red box were CAUTION — "Gemini-first," "extra LiteLLM hop." v2 paint them calm blue/purple:
those worry gone — we kept Claude via a clean provider, dropped Gemini.)*

---

## Middle — same ground under both 🌍

**SHARED FOUNDATION — A2A protocol · MCP · Vertex AI.** ADK sit ON these, not replace them.
v2 keep the same base; ADK add the agent layer. **One image `kga-v2` → four services.**

---

## THE OUTCOME — v2 go ADK-native across the board 🏁

- 🟩 **KEPT:** the deterministic pipeline + client gates. Custom `BaseAgent` wrap the crawl/distill/refine engine VERBATIM.
  gather → refine → approve → define → implement gates stay **client-owned** (human Yes/No). B0–B6 de-bias + `TPD_LLM_DETAIL` 1-call implement survive.
- 🟪 **CHANGED:** ADK-native serving + one gateway. 3 robot served `to_a2a(root_agent)`, A2A-only single-container.
  `mcp-gateway-v2` = single MCP endpoint, route each tool → A2A. Model via `ModelProvider(VertexClaude)`. Tasks in `DatabaseSessionService`.
- Two black code rock show it: left = custom ADK agent wrap engine; right = `to_a2a` + gateway routing.

---

## THE v2 MESH — one door, three robot, drawn 🕸️

**Claude Code → `mcp-gateway-v2` (blue hub) → { knowledge-gathering-v2 · test-plan-definition-v2 · test-evaluation-v2 } → SHARED MESH BACKING.**
All three robot are EQUAL now (`ADK to_a2a · A2A-only`) — no special one. Backing = Cloud SQL `kga-v2-taskstore` (`DatabaseSessionService`),
GCS `kga-v2-memory` bucket, Vertex `claude-sonnet-5`. Footer: **one image `kga-v2` → 4 Cloud Run services.**

---

## Rock color meaning 🎨

- 🟦 **light-blue box** = a2a / ADK service or agent (Claude Code, agents, glance boxes)
- 🟦 **strong-blue box** = the ONE `mcp-gateway-v2` hub (single MCP door)
- 🟪 **purple box** = LLM-loop / ModelProvider bits (agent LOOP, Claude-via-provider, CHANGED)
- 🟩 **green box** = shared foundation / KEPT pipeline / mesh backing
- ⬜ **grey box** = plain runtime / historical v1 detail / the "one image → 4 services" caption
- ⬛ **black box** = real code snippet
- **grey dashed line** = BEFORE↔NOW divider (VS)

---

## One grunt takeaway

**v1 diagram ASK "adopt ADK?" — v2 diagram SHOW "adopted, done."**
Whole stack ADK-native: robot served by `to_a2a`, model via `ModelProvider(VertexClaude)` (Gemini dropped),
ONE `mcp-gateway-v2` front three A2A-only robot, `DatabaseSessionService` hold the tasks.
Pipeline + human Yes/No gates KEPT; only the serving + model-door CHANGED. One image `kga-v2`, four services. 🔧✅

*(Sibling rock: `agents-swimlane-detail.*` = who-talk-who in order; `DESIGN-mcp-gateway-target.*` = the one-door blueprint.)*
