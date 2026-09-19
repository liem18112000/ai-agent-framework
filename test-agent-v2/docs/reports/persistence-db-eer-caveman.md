# persistence-db-eer.excalidraw — Caveman Explain

**Big idea: ONE pond hold all durable rock — one Cloud SQL Postgres, one engine
(`common.db.get_engine`), pgvector on. THREE clans live in same pond: rock WE carve,
rock ADK carve for us, rock A2A carve for us. Code-graph + lesson rock NOT here — they
sleep in GCS cave.** 🗄️🐘

---

## ① OUR ROCK — blue clan 🟦

We write this DDL ourself:
- **`memory_node`** — recall tier. `id PK`, `embedding vector(768)`, `tsv` = grown
  tsvector, `meta jsonb`. Big index: `HNSW(embedding)` + `GIN(tsv)`.
- **`memory_edge`** — memory graph. `PK (source_id, target)`. Point at `memory_node.id`
  but plain `text` → **app-level, no real FK**. Dashed line.
- **`prompt_template`** → **`prompt_version`** — template hold pointer `current_version`;
  version table = append-only log (audit). `key` = real FK. Solid line.

## ② ADK ROCK — green clan 🟩

`DatabaseSessionService` carve these ITSELF (we no touch DDL):
- **`sessions`** (`PK app_name,user_id,id`) ← **`events`** (`FK → sessions.id`, solid).
  One session, many event. Robot talk history live here.
- **`app_states`**, **`user_states`**, **`adk_internal_metadata`** — side state, tied by
  `app_name`/`user_id` (app-level, dashed).

## ③ A2A ROCK — orange clan 🟧

`DatabaseTaskStore` carve **`tasks`** — `id PK text(36)`, `context_id`,
`status`/`artifacts`/`history`/`metadata` all `json`. A2A task life sit here. Auto-made.

## ④ THE SECRET THREAD — ◈ context_id

`context_id` no real FK, but SAME word tie **A2A `tasks` ↔ ADK `sessions` ↔ `memory_node`**.
One pipeline run = one `context_id`. Follow the diamond ◈ to see clans hold hand across pond.

---

## Rock color meaning 🎨

- 🟦 **blue** = app-owned (memory + prompt store)
- 🟩 **green** = ADK `DatabaseSessionService` (auto-made)
- 🟧 **orange** = A2A `DatabaseTaskStore` (auto-made)
- **solid arrow** = real DB foreign key · **dashed arrow** = app-level ref (text cols, no FK)
- ◈ = `context_id` tie across clans (one pipeline context)

---

## One grunt takeaway

**One pond, one engine, three clans. WE own memory + prompt rock; ADK + A2A auto-carve
session + task rock in SAME pond. Solid = real FK, dashed = app-level, ◈ = the `context_id`
that ties it all. Code-graph + lesson NOT in pond — they in GCS cave.** 🐘👍

*(Sibling rocks: `two-tier-agent-memory-pgvector` = why the pond exist;
`cqrs-split-record-vs-recall` = write-wall vs read-pond split.)*
