# deployment-architecture.excalidraw — Caveman Explain

**Big idea: three robot live in cloud house. Human bang on guarded door to
wake robot. All three robot share ONE big storage cave. Same robot skin, same
cloud land.** 🦣☁️🤖

---

## Where robot live 🗺️

- **Cloud land** = GCP, tribe `klara-nonprod`.
- **Region** = `europe-west6` (cold mountain, far away).
- **Robot skin (image)** = `test-agent:e3c2a4c` — ALL robot wear same skin, just run different brain.

---

## Part 1 — How robot get born + put in house 🔨 (top-left, blue dashed rock)

**Deploy pipeline** = the robot factory.
- `deploy.sh` swing hammer → **Terraform + Cloud Build** cook the image → push to **Artifact Registry** (skin closet).
- Then dashed arrow: **"builds & applies image"** → shove robot into the cloud house. 📦→🏠

---

## Part 2 — Human talk to robot 🗣️ (top, orange rock)

**Claude Code (MCP client)** = human with talking-stick.
- Human NOT go inside robot house. Human shout through door (MCP).
- Talking-stick reach all THREE robot:
  - **solid rope** → knowledge-gathering + test-plan robot (MUST have). 🪢
  - **dashed rope** → test-evaluation robot (nice-to-have, optional). 〰️

---

## Part 3 — The three robot house 🏠🏠🏠 (big dashed box: Cloud Run · 3 services)

Each house SAME shape: **two robot-part in one hut.**

1. **Door guard (bridge)** 🛡️
   - Sit at `:8080`, path `/mcp`. This the ONLY door internet see (ingress).
   - **bearer-gated** = no token, no enter. Guard check password.
2. **Real worker robot (agent)** 🤖
   - Hide at `localhost:8081`, run **A2A server**. Internet NEVER see him direct.
   - Door guard whisper to worker over **A2A · localhost:8081** (inside hut only).

### The three robot, each got quirk 🪨

- **① knowledge-gathering-agent** (`knowledge_gathering:app`)
  → the ONLY robot allowed to walk OUTSIDE and read far rock. 🔍
- **② test-plan-definition-agent** (`test_plan_definition:app`)
  → slow thinker, get **600s** long-nap allowance before house kick him. ⏳
- **③ test-evaluation-agent** (`test_evaluation:app`)
  → **no Atlassian** — this robot never leave house, just judge quality. ⚖️

---

## Part 4 — The far rock only robot-① touch 🌍 (left, blue rock)

**Atlassian + Bitbucket** = far tribe's cave: **Jira · Confluence · repos.**
- Only **knowledge-gathering robot** walk there, and only **read-only crawl** — LOOK, no touch, no break. 👀🚫✋
- Live OUTSIDE the cloud house (external).

---

## Part 5 — Big shared storage cave 🗄️ (bottom dashed box: Shared backing · GCP)

All three robot walk DOWN and share same four rock. *(GCS memory · Cloud SQL tasks · Vertex · secrets.)*

- 🟢 **GCS bucket — memory bank** 📖
  Big truth book: notes · index · graphify. Where robot brain live.
- 🟢 **Cloud SQL — `kga-taskstore`** 📋
  Postgres rock. Hold **A2A task** list (who doing what job).
- 🟡 **Secret Manager — 5 secret** 🔑
  Locked box: bearer token · db password · atlassian · bitbucket key.
- 🟣 **Vertex AI — `claude-sonnet-5`** 🧠
  Big-brain oracle. Robot ask hard question, oracle answer.

---

## The whole trail (one grunt line) 🐾

**Human bang guarded door (:8080 /mcp, need token) → door guard whisper worker
robot (:8081 A2A) → worker read far Jira rock (only robot-①) + dig shared cave
(book, task, secret, oracle) → give answer back.** 🔁

---

## Rock color meaning 🎨

- 🔵 **light-blue guard** = bridge (the MCP door with password)
- 🔷 **dark-blue robot** = agent (the real A2A worker, hidden inside)
- 🟪 **purple dash** = one robot house (Cloud Run service wall)
- ⬜ **big grey dash** = the two big pens (Cloud Run pen, Shared-backing pen)
- 🟠 **orange** = human talking-stick (Claude Code MCP client)
- 🟢 **green** = storage that HOLD stuff (GCS book, Cloud SQL task)
- 🟡 **amber** = secret box
- 🟣 **violet** = Vertex brain-oracle

---

## One grunt takeaway

**3 robot, 1 skin, 1 cloud land. Every robot = guarded door + hidden worker.**
Only robot-① go outside (read Jira, no touch). Everybody share ONE cave (book +
task + secret + brain). Password on every door. Factory (`deploy.sh` + Terraform)
build robot and drop in house.
**Robot house locked tight. Human must bring token. 🔒🪙**

*(Sibling rock: `full-flow.excalidraw` = what robot DO; this rock = where robot LIVE.)*
