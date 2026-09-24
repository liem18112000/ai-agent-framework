# exec-multienv-db.excalidraw — Caveman Explain

**Big idea: run the SAME leaf against MANY caves — dev · staging · a Cloud Run revision · a
customer tenant. Each cave becomes a row on FIRST sight (dynamic, no pre-register). Store it
all in the SAME shared Cloud SQL (two new tables), heavy rocks stay in GCS. And the payoff:
with two caves you can DIFF them — consensus IS the oracle, no ground-truth needed.** 🦣🗺️🪨

**Status: BUILT — both tables ship on the shared Cloud SQL (text PKs, a `status` column). Env selection is explicit / from EXEC_ENVIRONMENTS; differential (2nd-env-as-oracle) mode is DEFERRED.** ✅

---

## ① ONE RUN, MANY CAVES 🟠→🔵 (orange fan-out, left)

**Test Executor `run_suite(ctx, env)`** (orange) fans out (orange arrows) to many caves
(light-blue):
- **dev** (`base_url: dev.svc`) · **staging** (`stg.svc`) · **rev:abc123** (a Cloud Run
  revision) · **tenant:42** (a customer).

*"New env → new row on first sight (dynamic)"* — the DB GROW as caves get tested; nobody
pre-registers them. 🌱

---

## ② DIFFERENTIAL — 2nd cave IS the oracle 🔀 (orange dashed double-arrow)

Between dev ↕ staging sit an **orange dashed double-arrow**: **differential mode** —
*same input, 2 caves → diff the responses → consensus IS the oracle.* No ground-truth
needed; the second cave judge the first. This is the concrete reason to store EVERY tested
cave. 🟠

---

## ③ THE TWO NEW TABLES 🪨 (dark navy boxes, green text, right)

Every run **upserts its env + inserts one run row** (green arrows) into the **shared Cloud
SQL Postgres (`common.db.get_engine`)** — the SAME engine behind the task store / sessions /
pgvector. Two new tables:
- **`exec_environment`** — `id` uuid PK · `context_id` · `name` (`'dev'|'rev:abc'|'tenant:42'`)
  · `base_url` · `revision` (image tag / git sha) · **`creds_ref` = Secret Mgr path (NOT the
  value!)** · `health` jsonb · `first/last_seen`.
- **`exec_run`** — `id` PK · `context_id` · `environment_id` → exec_environment · `state`
  (`in_progress|done|failed`) · `summary` jsonb · `signals` jsonb · `triage` per-scenario ·
  `trace_uri` (`gs://…/run_id/`, heavy → GCS).

*(Dark navy + green text = these are real schema rocks, not hand-wave boxes.)*

---

## The heavy/light split ⚖️ (blue note, bottom)

*"GCS holds traces/screenshots; Postgres holds the queryable metadata + trace_uri pointer."*
Same GCS-heavy / SQL-light split the rest of the system use — and why **NOT a new
datastore**: a redeploy once wiped loose GCS state, so the ledger lives on the durable
Postgres that already survived that.

---

## Rock color meaning 🎨

- 🟠 **orange** = the Test Executor + fan-out arrows + the differential dashed double-arrow + differential note
- 🔵 **light-blue** = the caves (dev/staging/rev/tenant) + the GCS heavy/light note
- 🟩 **dark-navy + green text** = the two NEW schema tables (`exec_environment` · `exec_run`) · green arrows = "every run upserts env + inserts run row"

---

## One grunt takeaway

**Same leaf, many caves; each cave a row on first sight; two new tables on the SAME Postgres
(no new store); creds stored as a Secret-Manager PATH not a value; heavy traces in GCS with
a `trace_uri` pointer. Two caves = free oracle: diff them, consensus decides.** **Still a
the tables are BUILT (text PK · status); only differential cross-env mode is still to come. 🗺️🪨

*(Sibling rocks: `exec-architecture` = where this Cloud SQL sits in the shared store ·
`exec-flow` = step 0 upserts the env / step 4 inserts the run row · `exec-tev-extension` =
who reads `exec_run.signals`.)*
