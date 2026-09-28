# two-tier-agent-memory-pgvector.excalidraw — Caveman Explain

**Big idea: robot brain get TWO layers. Layer one = the old cave-wall (GCS) — pile
all rock, never lie. Layer two = a smart pond (Cloud SQL + pgvector) that remembers
by MEANING, not by matching letters. Robot ask a question in ANY words and still find
the right rock.** 🧠🔀

**(v2 doc set — the two-tier CQRS design; names kept current.)**

---

## ① SYSTEM OF RECORD — the wall 🟦

`gs://…-ai-agent-memory/memory/` holds the truth pile:
- `notes/<type>/<id>.json + .md` · `insights / lessons (.json + .md)`
- `index/knowledge-index.json — hot blob, CAS` (the red rock = the hot one)
- `runs/*.md — append-only audit` · `refine/<ctx>: questions·answers·underst.`
- `learn/capture-queue.json`

**append-only · auditable · cheap · SOURCE OF TRUTH.** Write here first, always. 📥

---

## ② PROJECTOR — paint the pond on the SIDE 🟧🟦🟩🟪

- **enqueue IndexJob (O(1))** → return right now ⚡
- **drain worker** — head-of-next-req + background (off the write path)
- fork two little jobs: **metadata upsert** (cheap, no LLM) 🟩 + **Vertex embed**
  text-multilingual, thread-offloaded 🟪

🔴 *Red warning: Cloud Run throttles CPU after the response → embedding must live in the
DRAIN, NEVER the handler (serial Vertex calls once tripped ERROR_TIMEOUT).*

---

## ③ SYSTEM OF RECALL — the smart pond 🖤

Dark rock = the Postgres schema:
- **`memory_node`** — `id PK`, `synopsis` (embeddable text), `embedding vector(768)`
  (Vertex), `tsv` (full-text), `scope·status·confidence·run_id`, `content_uri → gs://`,
  `meta jsonb`. `INDEX hnsw` (vector), `INDEX gin(tsv)`, btree on type/scope/status.
- **`memory_edge`** (replaces `index.json`) — `source→target`, insert ON CONFLICT (no
  blob CAS).
- **`tasks` (existing A2A store)** sits in the SAME Cloud SQL for PostgreSQL 15 — reached
  via the Cloud SQL Python Connector (IAM + TLS). `CREATE EXTENSION vector`; scale-up path
  → AlloyDB + ScaNN.

One instance, reused. Task store + memory share the same pond. 🎯

---

## ④ HYBRID RETRIEVAL + DE-BIAS — the read path 🟧🟪🟦🟨🟩

Replaces the old substring `match_index_nodes`:

`query` → **embed query** → **hybrid candidates** (vector: `embedding ⇔ q` top-K ∪
`tsvector @@ plainto_tsquery`) → **SQL filters** (`status='active'·scope·run_id`) →
**B4 hub-penalty re-rank** 🟨 → **B5 grounding gate** (`memory_edge` n seed anchors) 🟨 →
**top-10 results** 🟩 → **Agent (KGA / TPD)**.

The bottom-left SQL rock shows the real recall: `WITH vec … ∪ lex … FULL OUTER JOIN …
/* RRF */ LIMIT 10`. So: **semantic ∪ lexical, filtered, then de-biased** — B4/B5 stop
memory from re-poisoning unrelated runs.

🔵 *Reversible: `MEMORY_BACKEND = gcs → hybrid → postgres`. Postgres down → recall FALLS
BACK to the GCS graph; the pipeline never breaks.*

---

## Rock color meaning 🎨

- 🟦 **blue** = GCS record layer · 🔴 **red** = the hot index blob
- 🟧 **orange** = enqueue / query start · 🟩 **green** = cheap metadata / final results
- 🟪 **purple** = Vertex embed / embed-query · 🖤 **dark** = Postgres schema + SQL
- 🟨 **yellow** = de-bias gates (B4 hub-penalty · B5 grounding)
- 🔵 **blue dashed** = reversible fallback · 🔴 **red text** = the CPU-throttle gotcha

---

## One grunt takeaway

**Write to wall (truth). Project to pond on the SIDE (never slow write). Ask pond by
MEANING (vector ∪ text ∪ SQL), then B4/B5 clean the noise.**
Pond down? Fall back to the wall — pipeline never break. Robot recall smart AND safe.
🧠🔀👍

*(Sibling rocks: `cqrs-split-record-vs-recall` = the split in one picture;
`self-learning-memory-loop` = the write side that feeds this pond.)*
