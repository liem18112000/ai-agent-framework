# deployment-architecture.excalidraw — Caveman Explain

**Big idea: NOW only ONE guarded door for whole tribe. Human bang that ONE
door (the gateway), gateway run inside and poke the right robot with A2A rope.
Three robot lost their own door-guard — they just work now. Four house, one
skin, one cloud land.** 🦣☁️🚪🤖

*(This the **v2** rock. v1 had three door — v2 squish them into one gateway.)*

---

## Where robot live 🗺️

- **Cloud land** = GCP, tribe `klara-nonprod`, region `europe-west6` (cold mountain).
- **Robot skin (image)** = `test-agent-v2:latest` — ONE image `kga-v2`, worn by ALL FOUR house.
- **ADK-native** = new robot bones. Robot served by ADK `to_a2a(root_agent)`.

---

## Part 1 — Robot factory 🔨 (top-left, blue dashed rock)

`deploy.sh` swing hammer → **Terraform + Cloud Build** cook the ONE image → push
to **Artifact Registry** → dashed arrow **"builds & applies image"** shove four
robot in the house. 📦→🏠 Same runtime spirit `kga-v2-runtime` for all.

---

## Part 2 — Human talk to ONE door 🗣️ (orange, top-center)

**Claude Code (MCP client)** = human with talking-stick.
- Human NOT bang three door no more. Human bang **ONE door** = the gateway.
- One orange rope → **`mcp-gateway-v2`**. Rope is **MCP** (`/mcp` :8080), need
  **GATEWAY_BEARER** token or no enter. 🪙

---

## Part 3 — The gateway boss 🚪 (big blue box in the middle)

**`mcp-gateway-v2`** = the ONLY MCP door the whole tribe show the world.
- Hold **3 upstream session**, one per robot.
- Every tool human ask → gateway **route it → A2A** to the right robot.
- Gateway whisper to robot with **A2A rope**, locked by **A2A_BEARER_TOKEN**. 🔒

---

## Part 4 — The three worker robot 🏠🏠🏠 (purple dashed pens, `4 services`)

No more door-guard + hidden-worker two-part hut. Each robot now **ONE box,
A2A-only**, run `uvicorn main:app`, listen **:8080**, gated by A2A_BEARER.

- **① knowledge-gathering-agent-v2** → the ONLY robot walk OUTSIDE, **read-only crawl**. 🔍
- **② test-plan-definition-agent-v2** → slow thinker, get **600s** long-nap. ⏳
- **③ test-evaluation-agent-v2** → **no Atlassian**, never leave house, just judge. ⚖️

---

## Part 5 — Far rock only robot-① touch 🌍 (left, blue rock)

**Atlassian + Bitbucket** = far tribe cave (Jira · Confluence · repos). Only
**knowledge-gathering robot** walk there, **LOOK no touch**. 👀🚫✋

---

## Part 6 — Big shared cave 🗄️ (bottom dashed box: Shared backing · GCP)

All robot walk DOWN, share four rock:

- 🟢 **GCS bucket — `kga-v2-memory`** 📖 truth book: notes · index · graphify.
- 🟢 **Cloud SQL — `kga-v2-taskstore`** 📋 Postgres. NOW hold **ADK sessions + tasks**
  (v2 own new store, ADK `DatabaseSessionService`).
- 🟡 **Secret Manager** 🔑 gateway+a2a bearer · db · atlassian · bitbucket.
- 🟣 **Vertex AI — `claude-sonnet-5`** 🧠 reached through **VertexClaudeProvider**
  (the one model plug; Gemini backend gone).

---

## Rock color meaning 🎨

- 🟠 **orange** = human talking-stick (Claude Code MCP client)
- 🔵 **strong blue** = the ONE gateway door (mcp-gateway-v2)
- 🩵 **light blue** = a worker robot (A2A-only agent) + the far Atlassian cave
- 🟪 **purple dash** = one robot house (Cloud Run service wall)
- ⬜ **big grey dash** = the two big pen (Cloud Run pen, Shared-backing pen)
- 🟢 **green** = storage that HOLD stuff (GCS book, Cloud SQL store)
- 🟡 **amber** = secret box
- 🟣 **violet** = Vertex brain-oracle

---

## One grunt takeaway

**v2 = ONE door, not three. Human bring GATEWAY_BEARER, bang `mcp-gateway-v2`
(:8080 /mcp). Gateway run inside, poke right robot over A2A (A2A_BEARER).**
Robot now naked worker — no own door-guard. Four house, one `kga-v2` skin.
Everybody share the cave (kga-v2-memory book + kga-v2-taskstore + secret + Vertex brain).
**One password door for whole tribe. 🔒🚪**

*(Sibling rock: `full-flow.excalidraw` = what robot DO; this rock = where robot LIVE.)*
