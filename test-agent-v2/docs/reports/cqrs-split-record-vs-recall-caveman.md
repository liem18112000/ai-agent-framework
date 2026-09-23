# cqrs-split-record-vs-recall.excalidraw — Caveman Explain

**Big idea: DON'T throw away the old cave-wall. KEEP the wall (GCS) as the one TRUE
story-log — write-only, cheap, never lie. Then PAINT a fast picture of it in a
smart pond (Cloud SQL + pgvector) that robot can ASK questions to. Two rooms, one
truth.** 🪨💧

**(v2 doc set — the CQRS split; names kept current.)**

---

## ✍️ Left room — WRITE / SYSTEM OF RECORD 🟦

Every step-handler DROPS a rock here (the "C" in CQRS — command). This is **GCS, the
raw event / artifact log**:
- `notes/<type>/<id>.json` + `.md` — the facts robot gather
- `insights / lessons` `.json` + `.md`
- `index/knowledge-index.json` — hot blob (CAS)
- `runs/*.md` — append-only audit trail
- `refine/<ctx>` — questions · answers · understanding
- `learn/capture-queue.json`

Green badge: **append-only · auditable · cheap · SOURCE OF TRUTH · unchanged.** Robot
never edit, never delete. Just pile more rock. 📥

---

## 🔮 Middle — PROJECTOR (async) 🟪

Little worker sit in the middle. It **project** the pile into the smart pond, OFF to
the side (async — never slow the write). One dashed grey line runs BACK carrying
`content_uri` (the pond points home to the blob). One dashed green line = **rebuild ▶
backfill §8** (re-pour the whole pond from the wall any time).

---

## 🔎 Right room — READ / SYSTEM OF RECALL 🟪

Robot ASK its questions here (the "Q" in CQRS — query). This is **Cloud SQL + pgvector,
the queryable view**:
- `memory_node` — embedding `vector(768)` · `tsv` · meta
- `content_uri → gs://` pointer back to the blob
- `memory_edge (source→target)` — replaces `index.json`
- **hybrid recall: vector ∪ full-text ∪ SQL filters**
- **B4 hub-penalty + B5 grounding on the re-rank** (de-bias survive)
- async backfill · content-hash skip — never blocks a write

Purple badge: **materialized view · rebuildable · lean — GCS holds the mass.** The pond
is thin and re-pourable; the wall holds the weight. 🎯

---

## 🧱 Bottom band — why it safe

Same event-sourcing shape the pipeline already lean on: **GCS is the LOG · the DB is
the VIEW.** Postgres is a projection — droppable and re-derivable from GCS, so a DB
outage just degrades recall to today's graph-JSON fallback and **never breaks the
pipeline.** Feature-flagged · backfillable · reversible.

---

## Rock color meaning 🎨

- 🟧 **orange ellipse** = WRITE (command) · 🟩 **green ellipse** = READ (query)
- 🟦 **blue box** = GCS write-model (system of RECORD)
- 🟪 **purple box** = pgvector read-model (system of RECALL) + the PROJECTOR
- 🟩 **green badge** = source-of-truth props · 🟪 **purple badge** = view props
- ⬜ **grey dashed** = `content_uri` pointer home · 🟢 **green dashed** = rebuild / backfill

---

## One grunt takeaway

**Wall = truth (write-only, cheap, never lie). Pond = fast picture of the wall (ask it
anything). Projector paints pond from wall on the side.**
Pond dry up? Re-pour from wall. Wall never break. Robot recall by MEANING, truth stay
safe. 🪨💧👍

*(Sibling rock: `two-tier-agent-memory-pgvector` = the same split drawn in full plumbing.)*
