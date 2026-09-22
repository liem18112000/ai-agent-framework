# Run History, Memory Introspection & Memory Admin

**Purpose.** Add a standalone **memory & history admin utility** — for operators, **not part of the
testing process**. It tracks memory/run history and acts on it. Shape (chosen): a **dedicated
`admin_agent` Cloud Run service** (a deterministic router, no LLM), whose tools register on the
existing testing-agent gateway under a clearly-marked **`[ADMIN — non-pipeline]`** group. Four
capabilities:

1. **Run history** — list every past pipeline run and show one run's full test detail in a
   structured form.
2. **Memory introspection** — view all four agent-memory tiers (working / episodic / semantic /
   procedural) that actually exist in this system.
3. **Wipe-all** *(destructive tool #1)* — clear the A2A task store **and** the memory bank in one
   guarded call.
4. **Backup memory as a version** *(tool #2)* — snapshot the memory bank to a timestamped, summarised
   version.

> House style matches the sibling `PLAN-*.md`: TL;DR + principle, glossary, current anatomy, the one
> enabler, feature-by-feature design, wiring, phased roadmap, constraints, and a test plan.

---

## 0. TL;DR — four features, one enabler

**Where we are.** The gateway fronts three A2A agents (KGA, TPD, TEV). Memory lives in a GCS
`MemoryBank` (`memory/**`), a pgvector recall tier (`memory_node`/`memory_edge`), and a shared
Cloud SQL engine that also backs the ADK `DatabaseSessionService` and the A2A `DatabaseTaskStore`.
There is **no way to list what ran before, no way to inspect the memory tiers, and no way to reset or
snapshot memory** — the read tools (`search_memory`, `get_note`, `search_lessons`) only work when you
already know the id.

**The one enabler.** Three of the four features need to *enumerate* and *remove* blobs. The
`ObjectStore` port (`common/store/object_store.py`) today exposes only `blob(path)` and
`get_blob(path)` — **no `list`, no `delete`**. Adding two methods to the port (and its two live
adapters, GCS + in-memory) unlocks run-enumeration, wipe, and backup at once. This is the load-bearing change; everything else is
a read-aggregator or a copy loop over it.

**The principle (introspection, not new truth).** These tools **read, reset, or copy state that
already exists** — they never invent a new source of truth. A "run" is just a `context_id`; its detail
is the union of artifacts the pipeline already wrote under that id. The memory tiers already exist —
the tool only *names and surfaces* them. Wipe and backup operate on the GCS bank (the source of truth)
and the shared engine (the task/session store); pgvector is a **rebuildable projection**, handled
accordingly.

**A utility, cleanly separated from the pipeline.** These verbs are for an admin, not the test flow,
so they get their **own agent** (`admin_agent`) rather than being bolted onto a pipeline agent —
homing "wipe the task store" inside `knowledge_gathering` would blur the boundary the request draws.
The one endpoint is kept for the operator's convenience: `admin_agent`'s tools register on the
existing gateway in a **marked `[ADMIN — non-pipeline]` group**, so the pipeline surface (`gather →
… → implement`) and the admin surface are visibly distinct in one client.

**A deterministic router, not an LLM sub-agent.** `admin_agent` is an A2A/ADK `BaseAgent` router
(the same shape as `KgaRouter`) with **no LLM** — all four features are deterministic aggregation /
SQL / blob work, so an LLM hop would only add latency and non-determinism. It has `build_bank()` (GCS)
and `get_engine()` (SQL) in scope via `to_a2a`/`build_runner`, exactly as the pipeline agents do.

| # | Feature | New tool(s) | Reads / touches | Destructive? |
|---|---|---|---|---|
| F1 | Run history | `list_runs`, `get_run` | GCS `memory/refine/**`, `memory/runs/**`, pack/plan/scenarios | no |
| F2 | Memory view | `view_memory` | session store, run logs, lessons, index, pgvector, prompts | no |
| F3 | Wipe-all | `wipe_all` | task store + session store + `memory/**` + pgvector | **YES** |
| F4 | Backup | `backup_memory`, `list_backups` | copies `memory/**` → `memory-backups/**` | no |

> **Scope trim (post-ponytail review).** `restore_backup` (a destructive read-back) is **deferred** —
> the request was "backup as version", i.e. write. An admin restores a version with `gsutil cp` until a
> real restore need appears. `wipe_all` has **no `scope` selector** (one combined wipe, as asked) and
> `list_runs`/`get_run` have **no `format` toggle** (return markdown). These were speculative
> flexibility; add them when a caller actually needs them.

---

## 1. Concepts & terms — the four memory tiers, mapped to *this* system

The request lists four canonical agent-memory types. Each maps to something concrete already in the
codebase (this mapping *is* the F2 design):

| Canonical type | Textbook definition | Where it lives here | Read path |
|---|---|---|---|
| **Working (in-context)** | Live scratchpad for the current task; resets at session end. | ADK session state in `DatabaseSessionService` (Cloud SQL) **+** per-context refine state: `memory/refine/<ctx>/{state,questions,answers}.json`, `understanding.md`. | `session_service`, `MemoryBank.read_refine_state/read_questions/read_answers/read_understanding` |
| **Episodic** | What happened, when, outcome — a history of past events. | Run logs `memory/runs/<started>_run-<id>.md` & `_refine-<id>.md`; captured lessons = `Insight`s of kind `lesson`/`correction`/`gotcha` under `memory/notes/insight/`; A2A task lifecycle rows in `DatabaseTaskStore`. | `learn.iter_lessons`, blob listing of `memory/runs/`, task-store query |
| **Semantic** | Generalised, timeless facts about the domain. | Knowledge graph index `memory/index/knowledge-index.json` + distilled notes `memory/notes/<type>/*` + the pgvector `memory_node`/`memory_edge` tables. | `MemoryBank.load_index`, `retrieve.search_nodes`, `PgMemoryStore` |
| **Procedural** | How the agent operates — rules, skills, workflows. | Agent instructions/prompts (`common/bridge/prompts.py`, each agent's system prompt), tool definitions, interrogation round classes (`common/interrogate/round/*`), the assured-loop rubric. | Static enumeration (agent names + tool names + round list); no DB |

**Why the mapping matters.** F2 is not "build a memory system" — it is "point a read tool at each of
the four things that already exist". Working/episodic/semantic are queryable at runtime; procedural is
mostly static code/prompts, so `view_memory("procedural")` enumerates the agents, their registered
tool names, and the interrogation rounds rather than dumping a database.

Other terms:

| Term | Definition |
|---|---|
| **Run** | One `context_id` (e.g. `run-6f2a…`). All pipeline artifacts for a ticket hang off this single id — the gateway already tells clients to *"reuse the one context_id for every later call"*. |
| **Run index** | The list of known runs. **Computed on the fly** by listing `memory/refine/*/` (one dir per context) — *not* a maintained sidecar file (see §3, "no dual source of truth"). |
| **Version (backup)** | A prefixed copy of `memory/**` at `memory-backups/<UTC-datetime>_<slug(summary)>/…`, plus a `MANIFEST.json` (datetime, summary, blob count, byte size). |
| **Rebuildable projection** | pgvector is derived from the GCS bank via `pg/backfill.py`. Backup skips it (rebuild from the restored bank); wipe truncates it (it re-fills on next gather/backfill). |

---

## 2. Current anatomy — what already exists (and is reused verbatim)

```
Gateway (src/gateway/mcp_server.py)
  ├─ register_kga → search_memory, get_note, search_lessons, veto_lesson,
  │                 gather_knowledge, refine, get_questions, get_understanding, approve
  ├─ register_tpd → define_plan, get_plan, approve_plan, implement_plan, get_scenarios, get_coverage
  ├─ register_tev → evaluate_pack, evaluate_plan
  ├─ register_admin → [ADMIN] list_runs, get_run, view_memory, backup_memory,   ← NEW (this plan)
  │                   list_backups, wipe_all
  └─ direct       → agent_cards, send_raw_{kga,tpd,tev}

KGA / TPD / TEV processes (main:app, AGENT=…)  — the pipeline agents (unchanged)

admin_agent process (main:app, AGENT=admin_agent)  ← NEW dedicated utility service
  ├─ AdminRouter (admin_agent/agent.py) — text-dispatch: "list-runs …", "view-memory …",
  │                 "wipe-all …", "backup-memory …" → common.admin (BaseAgent router, no LLM)
  ├─ build_bank() → MemoryBank over the ObjectStore (GCS)                  [GCS memory access]
  └─ Runner via to_a2a → get_engine() → DatabaseSessionService + DatabaseTaskStore  [DB access]

MemoryBank (common/memory/bank.py) — GCS layout:
  memory/index/knowledge-index.{json,md}          semantic index
  memory/notes/<type>/<slug>.{json,md}            distilled notes + insights (lessons)
  memory/runs/<started>_run-<id>.md               episodic run logs
  memory/runs/<started>_refine-<id>.md
  memory/refine/<ctx>/{state,questions,answers}.json + understanding.md   working state per run
  memory/refine/_sessions/<a2a_id>.json           a2a-id → pack context_id map

Shared Cloud SQL engine (common/db.py get_engine)
  ├─ DatabaseSessionService  (ADK sessions — working memory)
  ├─ DatabaseTaskStore       (A2A task lifecycle — episodic)
  └─ memory_node / memory_edge (pgvector — semantic recall)

Store adapters (common/store/): gcs.py · local.py · memory.py — all duck-type the ObjectStore port
Lessons: common/learn/{store,govern}.py — iter_lessons / veto_lesson over the index
```

**Reused verbatim (no change):** `MemoryBank` read methods, `learn.iter_lessons`, `retrieve.search_nodes`,
`PgMemoryStore`, `get_engine`, `pg/backfill.py`, the KGA text-dispatch router pattern, the gateway
`register_tools(mcp, session) -> dict` pattern.

---

## 3. The one enabler — extend the `ObjectStore` port with `iter_blobs` + `delete`

Everything in F1/F3/F4 needs to *list* and (for F3) *delete* blobs by prefix. Add exactly two methods
to the port and implement them in the **two adapters actually in use** — `GcsObjectStore` (prod) and
`InMemoryObjectStore` (tests). `LocalObjectStore` (`STORE_BACKEND=local`) has no caller today, so it
raises `NotImplementedError` until something selects that backend. Keep the port stdlib-only (still
importable offline).

```python
# common/store/object_store.py  (add to the ObjectStore Protocol)
def iter_blobs(self, prefix: str) -> Iterable[Blob]:
    """Yield every blob whose path starts with `prefix` (empty prefix = all). Each has `.name`."""
    ...

def delete(self, path: str) -> bool:
    """Delete the blob at `path`. Return True if it existed. Idempotent (missing → False)."""
    ...
```

Adapter implementations (small, each obvious):

| Adapter | `iter_blobs(prefix)` | `delete(path)` |
|---|---|---|
| `GcsObjectStore` | `self._bucket.list_blobs(prefix=prefix)` wrapped as `_GcsBlob` | `blob.delete()`, swallow `NotFound` → `False` |
| `InMemoryObjectStore` | filter `self.store` keys by prefix | `pop` from `store` + `gens` |
| `LocalObjectStore` | **deferred** — `raise NotImplementedError` (no caller) | **deferred** |

Add `name` to `_GcsBlob`/`_InMemoryBlob` so callers can read a blob's path when iterating. A
`delete_prefix(prefix) -> int` convenience on `MemoryBank` (loop `iter_blobs` → `delete`) keeps the
wipe + backup callers one line — this is the *one* new bank method (the backup copy loop lives in
`common/admin.py`, not the bank, so the already-large `MemoryBank` doesn't grow further).

> **Why not maintain a `run_index.json` sidecar instead of listing?** A maintained index is a second
> source of truth that drifts the moment any write path forgets to update it, and it needs a CAS
> loop of its own. Listing `memory/refine/*/` is O(runs) once per `list_runs` call, on an operator
> tool that runs rarely. **Compute on read; add a projection only if listing is measurably slow.**
> (YAGNI — `# ponytail: list-on-read; add run_index.json projection if list_runs gets slow.`)

---

## 4. Feature designs

All handler logic lives in **one new module `common/admin.py`** (pure functions taking `bank` and/or
`engine`), reused by the KGA router and directly testable offline against `InMemoryObjectStore`. The
gateway tools are thin forwarders; the KGA router dispatches new command prefixes to `common.admin`
exactly like it dispatches `search-memory` today.

### F1 — Run history & detail

**`list_runs(limit=50) -> str`** — enumerate `memory/refine/*/` prefixes → one `RunSummary` per
context, newest first. Each summary is cheap (read the small json sidecars, not note bodies):

```
RunSummary: context_id · seed/ticket · started · ended · refine_done(bool)
            · questions(n)/answered(n) · pack_nodes(n) · plan_status · scenarios(n)
            · eval_pack_score? · eval_plan_score? · lessons(n)
```

Sources per field: `refine/<ctx>/state.json` (seed, started, done), `questions.json`/`answers.json`
(counts), `understanding.md` (present?), the graph index filtered by `context_id`/`run_id` (pack &
lessons), plan/scenarios via the TPD read path (or the plan blob if the TPD state is GCS-backed).
Render as a markdown table (default) or JSON.

**`get_run(context_id) -> str`** — the full structured test detail for one run, aggregating the
existing read tools under one id:
- **Understanding brief** (`read_understanding`)
- **Q&A** (`read_questions` + `read_answers`)
- **Pack** (index nodes/edges scoped to the context; node kinds breakdown)
- **Test plan** (`get-test-plan` via TPD)
- **Scenarios + steps** (`get-scenarios` via TPD)
- **Coverage matrix** (`get-coverage` via TPD)
- **Evaluations** (pack/plan scores if `evaluate_*` ran)
- **Run logs** (matching `memory/runs/*run-<id>*`)
- **Lessons captured** during the run

This is a *composition* of calls that already exist — F1's only genuinely new code is the enumeration
(`list_runs`) built on §3. `get_run` is mostly orchestration + a `RunDetail` render.

> **Structured form.** `RunSummary`/`RunDetail` are stdlib `@dataclass`es rendered to **markdown**,
> matching how `RunLog`/`Note` already serialise. No new persistence, no `format` toggle (the client is
> an LLM reading a string — add a JSON mode only if a non-LLM caller appears).

### F2 — View all memory types (`view_memory`)

**`view_memory(tier="all", context_id=None) -> str`** — one structured report per tier (§1 mapping):

- **working** — ADK session state for `context_id` (via `session_service.get_session`) + the refine
  working set (`state/questions/answers/understanding`). Requires `context_id`; without it, lists
  active sessions.
- **episodic** — most-recent N run logs (list `memory/runs/`) + the lessons list
  (`learn.search_lessons`) + A2A task count/states for the context.
- **semantic** — index summary (node count by `type`, edge count) + pgvector row counts
  (`SELECT count(*) … memory_node/memory_edge`) + top nodes for an optional query
  (`retrieve.search_nodes`). Flags GCS↔pgvector drift (index node count vs `memory_node` count) —
  a cheap, genuinely useful health signal.
- **procedural** — enumerate the three agents (names + one-line role), their **registered tool
  names** (from each `register_tools` dict), the **interrogation rounds** (`common/interrogate/round/*`),
  and the assured-loop rubric name. Static; no DB read.

`tier="all"` runs each section (skipping working when no `context_id`). Read-only; never blocks.

### F3 — Wipe-all *(destructive tool #1)*

**`wipe_all(confirm: str) -> str`** — clears task store **and** memory in one call (the request pairs
them; no `scope` selector until someone needs to wipe just one). This is a trust boundary — **not lazy
about the guard**:

- **Guarded:** requires `confirm` to equal a literal token the tool states in its docstring/error
  (e.g. `"WIPE"` or the GCS bucket name). No token → refuse with the exact token to pass. (MCP
  elicitation is broken over HTTP in this stack per the memory notes, so the confirm is a **required
  argument**, not a server-driven prompt.)
- **What it clears** (all three, always):
  1. **Memory bank** — `bank.delete_prefix("memory/")` (notes, index, runs, refine, lessons queue).
     Skips `memory-backups/**` — backups survive a wipe on purpose.
  2. **pgvector** — `TRUNCATE memory_node, memory_edge` (rebuildable; safe to truncate).
  3. **Task store + sessions** — `TRUNCATE` the A2A task table(s) and the ADK session/event tables on
     the shared engine. (Discover exact table names once via `inspect(engine)`; TRUNCATE over DROP so
     `to_a2a`/`DatabaseSessionService` don't have to recreate schema on next boot.)
- **Returns** a per-target report (rows/blobs removed). **Idempotent** — a second call is a no-op
  count.

> `# ponytail: TRUNCATE not DROP — schema recreation on cold-start is the 3am page.`

### F4 — Backup memory as a version *(tool #2)*

**`backup_memory(summary: str) -> str`** — snapshot the GCS bank to a timestamped version. The copy
loop lives in `common/admin.py` (over §3 `iter_blobs`), not on `MemoryBank`:
- **Version id:** `<UTC-iso-datetime>_<slug(summary)>` (datetime from `datetime.now(UTC)` in the
  `admin_agent` process — real clock available server-side; the slug reuses `bank._slug`).
- **Copy:** every blob under `memory/` (excluding `memory-backups/`) → `memory-backups/<version>/…`
  preserving relative paths. GCS: prefer `bucket.copy_blob` (server-side, no download); in-memory:
  read+write.
- **Manifest:** write `memory-backups/<version>/MANIFEST.json` = `{datetime, summary, blob_count,
  byte_size, source_prefix}`.
- **pgvector:** *not* copied — it rebuilds from the bank via `pg/backfill.py`. The manifest notes this.

**`list_backups() -> str`** — read every `memory-backups/*/MANIFEST.json`, newest first. Trivial
(~3 lines) and makes the versions discoverable; ships with `backup_memory`.

> **Deferred: `restore_backup`.** The request is "backup as version" (write), and a versioned copy is
> restorable manually (`gsutil cp memory-backups/<version>/memory/** → memory/`, then a `backfill` to
> rebuild pgvector). Building a *destructive* read-back nobody asked for is speculative scope — add it
> when a restore need is real, gated behind the F3 confirm token.
> `# ponytail: back up the source of truth (GCS); pgvector is a projection, rebuild don't copy.`

---

## 5. Where it lives & wiring

**A dedicated `admin_agent` service; its tools registered on the existing gateway in a marked ADMIN
group.** Reuse the existing router + `register_tools` patterns verbatim — no new *pattern*, just a
fourth agent of the same shape.

1. **`common/admin.py`** — pure handler functions:
   `list_runs`, `get_run`, `view_memory`, `wipe_all`, `backup_memory`, `list_backups` (6; `restore_backup`
   deferred). Each takes `bank` (and, for wipe/pg views, `engine = get_engine()`). Framework-neutral,
   offline-testable.
2. **`common/store/*`** — the §3 port extension (`iter_blobs`, `delete`) + `MemoryBank.delete_prefix`.
3. **`admin_agent/agent.py`** — a new `AdminRouter(BaseAgent)` (mirrors `KgaRouter`): dispatch the
   command prefixes (`"list-runs"`, `"get-run"`, `"view-memory"`, `"wipe-all"`, `"backup-memory"`,
   `"list-backups"`) → call `common.admin.*` off the event loop via
   `asyncio.to_thread` (GCS + sync SQLAlchemy are blocking — mirrors `_refine_state`). No LLM, no
   sub-agents. `root_agent = AdminRouter(name="admin_agent")`. It serves via the existing `main.py`
   (`AGENT=admin_agent` → `to_a2a` + `build_runner` + `build_task_store` + bearer auth, for free).
4. **`admin_agent/bridge/mcp_server.py`** — `register_tools(mcp, session) -> dict` with the six thin
   `@mcp.tool()` forwarders, each `(await session.ask(f"list-runs {…}")).text`. Every docstring is
   prefixed **`[ADMIN — not part of the testing pipeline]`**; `wipe_all` states the required confirm token.
5. **Gateway (`gateway/mcp_server.py`)** — add `ADMIN_A2A_URL` (default `http://localhost:8084/`),
   `admin_session = BridgeSession(ADMIN_A2A_URL, TOKEN)`, `**register_admin(mcp, admin_session)` into
   `_tools`, and `admin_session` into `_CARDS`. `INSTRUCTIONS` gains one paragraph: an **ADMIN /
   utility** group that is *not* part of `gather → … → implement`; `wipe_all` is destructive and needs
   the confirm token; the client asks the user Yes/No first (same client-owned-gate convention as the
   pipeline).
6. **Deploy (`deployments/`)** — a `module.admin` Cloud Run service like `module.kga` (image, env:
   `AGENT=admin_agent`, `GCS_BUCKET`, DB creds, `A2A_BEARER_TOKEN`), its own **`allUsers`/invoker IAM**
   binding, and `ADMIN_A2A_URL` wired into the gateway service. `main.py::_REQUIRED_ENV` gains
   `admin_agent → ("GCS_BUCKET",)` (DB optional; degrades to in-memory task store).

**Why a dedicated agent (not the gateway process, not KGA):** the request draws the boundary —
this is an *admin utility, not a pipeline step*. A dedicated `admin_agent` keeps destructive verbs out
of `knowledge_gathering` while reusing the identical serving stack (`main.py`, `to_a2a`, bank, engine).
The gateway stays a pure HTTP bridge (no GCS/DB env of its own). Cost is **one extra Cloud Run
service**; the payoff is a clean, independently-securable admin surface (its own service can carry
tighter IAM than the public pipeline agents).

---

## 6. Phased roadmap

| Phase | Deliverable | Depends on | Risk |
|---|---|---|---|
| **A0 — enabler** | `ObjectStore.iter_blobs` + `delete` on the port + GCS/InMemory adapters (Local deferred); `MemoryBank.delete_prefix`; `.name` on GCS/InMemory blobs. Unit tests on `InMemoryObjectStore`. | — | low |
| **A1 — admin agent scaffold** | `admin_agent/agent.py` (`AdminRouter`, no LLM) + `admin_agent/bridge/mcp_server.py` (`register_admin`); wire `ADMIN_A2A_URL`/`admin_session` into the gateway + `_REQUIRED_ENV`. Empty dispatch first; A2A round-trip test via lifespan (per `to_a2a` note). | — | low |
| **A2 — F1 read** | `common.admin.list_runs` / `get_run` + `RunSummary`/`RunDetail`; dispatch + `[ADMIN]` tools. | A0, A1 | low |
| **A3 — F2 view** | `common.admin.view_memory` (4 tiers) + dispatch + tool. | A0, A1, `get_engine` | low |
| **A4 — F4 backup** | `backup_memory` + `list_backups` + dispatch + tools (`restore_backup` deferred). | A0, A1 | low |
| **A5 — F3 wipe** | `wipe_all` (guarded, per-target report) + dispatch + tool; discover exact task/session table names. | A0, A1, A4 (so a wipe is recoverable) | **high (destructive)** |
| **A6 — deploy** | `module.admin` Cloud Run service in `deployments/` (env, invoker IAM), `ADMIN_A2A_URL` into the gateway; build image before creating the service (per the v2-deploy note). | A1–A5 | med |
| **A7 — docs** | Gateway `INSTRUCTIONS` + `USAGE.md` entries; note the `[ADMIN]` group + confirm tokens + the new endpoint URL. | A1–A6 | low |

Order rationale: enabler + agent scaffold first (an empty, deployable service de-risks the topology);
**backup (A4) before wipe (A5)** so wipe is always recoverable from a version; F1/F2 (pure reads) land
early and exercise the enabler before any destructive verb.

---

## 7. Constraints this system's own history imposes

- **Task/session table names are not ours** — they belong to `a2a-sdk` (`DatabaseTaskStore`) and ADK
  (`DatabaseSessionService`). Discover them at runtime with `sqlalchemy.inspect(engine)` and TRUNCATE
  by reflected name; don't hard-code a guessed schema. (`gitStatus`/memory: task store table was
  created lazily by the first gather.)
- **pgvector is a projection, never the truth** — the GCS bank is authoritative (`two-tier` note).
  Wipe truncates pgvector; backup skips it; restore rebuilds via `pg/backfill.py`. Never back up
  pgvector *instead of* GCS.
- **Blocking I/O off the event loop** — GCS and sync SQLAlchemy calls must run via `asyncio.to_thread`
  in the async router, or they stall Cloud Run liveness (`implement serial Vertex calls` note).
- **MCP elicitation is broken over HTTP here** — the destructive confirm must be a **required tool
  argument**, not a server-driven `ctx.elicit` prompt (`mcp-elicitation-http` note).
- **Redeploy loses Cloud Run in-memory state** — when no DB is configured, session/task stores are
  in-memory and `wipe_all` on the task store is a no-op (nothing persisted). Report that honestly
  rather than claiming a wipe (`test-plan scenario-generator gotchas` note: a redeploy already lost
  GCS-less memory once).
- **Backups must survive a wipe** — `wipe_all` deletes `memory/**` only, never `memory-backups/**`.
- **Object-name limits** — backup keys are `memory-backups/<version>/<original-key>`; `<version>`
  adds ~40 chars, and original keys are already `_slug`-bounded to 200, so the sum stays well under
  GCS's 1024-char limit.
- **New service = new IAM to (re)apply** — a `terraform -replace` of a Cloud Run service drops its
  `allUsers`/invoker binding; the `module.admin` service needs its own invoker `iam_member`, and the
  gateway must be able to reach `ADMIN_A2A_URL` (`Cloud Run -replace wipes IAM` note). Build the image
  **before** creating the service, or the placeholder container can't start (`v2-deploy collides`
  note). A 2Gi memory default is safer than 512Mi for anything touching the bank (`v2 agents need 2Gi`
  note) — though the admin agent is lighter than a gather.
- **`to_a2a` routes need lifespan startup** — the `admin_agent` A2A round-trip test must wrap calls in
  `async with app.router.lifespan_context(app)` (the `POST /` route is attached only at ASGI startup),
  per the `to-a2a-routes-need-lifespan-startup` note.
- **`.env` leaks Vertex into offline tests** — `admin_agent` needs no model, but if its `__init__`
  runs `load_dotenv()`, keep the session-scoped `_offline_default_no_vertex` conftest clear so admin
  tests don't accidentally dial Vertex (`dotenv-leaks-vertex` note).

---

## 8. Test plan (offline, `InMemoryObjectStore` + fake engine)

- **A0:** `iter_blobs(prefix)` returns exactly the matching keys; `delete` is idempotent
  (True then False); `delete_prefix` count == blobs removed; `iter_blobs("")` == all.
- **F1:** seed a fake bank with two contexts' refine dirs → `list_runs` returns both newest-first with
  correct counts; `get_run` composes understanding + Q&A + pack for one context; unknown context → a
  clean "no such run" message.
- **F2:** each tier renders without a live DB (semantic/episodic degrade gracefully when
  `get_engine()` is None); `procedural` lists the known tool names.
- **F3:** `wipe_all("")` refuses and echoes the required token; `wipe_all(<token>)` empties
  `memory/**` but leaves `memory-backups/**`; second call reports zero; no-DB → task-store step
  reports "in-memory, nothing persisted".
- **F4:** `backup_memory("x")` copies every `memory/**` blob under `memory-backups/<version>/` + writes
  a manifest with the right count; a second backup makes a distinct version; `list_backups` finds both,
  newest-first. Datetime is injectable for deterministic assertions.

Every non-trivial handler leaves one runnable assert-based check behind (the ponytail rule); no new
framework or fixtures beyond the existing `InMemoryObjectStore`.

---

## Appendix A — new tool surface (gateway MCP, `[ADMIN — non-pipeline]` group)

```
list_runs(limit: int = 50) -> str
get_run(context_id: str) -> str
view_memory(tier: str = "all", context_id: str | None = None) -> str   # all|working|episodic|semantic|procedural
backup_memory(summary: str) -> str
list_backups() -> str
wipe_all(confirm: str) -> str                              # destructive — confirm token required
# deferred: restore_backup(version, confirm)              — add when a restore need is real (manual gsutil cp meanwhile)
```

## Appendix B — GCS layout after this change

```
memory/**                                   (unchanged — the live bank)
memory-backups/<UTC-datetime>_<slug>/       one versioned snapshot per backup
  ├─ MANIFEST.json                          {datetime, summary, blob_count, byte_size, source_prefix}
  └─ memory/**                              verbatim copy of the bank at backup time
```

## Appendix C — files touched

```
NEW  src/common/admin.py                    6 handlers + backup copy loop (pure fns over bank/engine); restore deferred
NEW  src/admin_agent/__init__.py
NEW  src/admin_agent/agent.py               AdminRouter(BaseAgent), no LLM; root_agent; dispatch → common.admin
NEW  src/admin_agent/bridge/__init__.py
NEW  src/admin_agent/bridge/mcp_server.py   register_admin(mcp, session): 6 thin [ADMIN] @mcp.tool forwarders
EDIT src/common/store/object_store.py       + iter_blobs, delete on the port
EDIT src/common/store/{gcs,memory}.py       + iter_blobs, delete; + .name on blobs  (local.py: NotImplementedError)
EDIT src/common/memory/bank.py              + delete_prefix  (one method; copy loop lives in admin.py)
EDIT main.py                                _REQUIRED_ENV += {"admin_agent": ("GCS_BUCKET",)}  (serving is generic)
EDIT src/gateway/mcp_server.py              + ADMIN_A2A_URL, admin_session, register_admin, _CARDS; INSTRUCTIONS: [ADMIN] group + confirm tokens
EDIT deployments/…                          + module.admin Cloud Run service, invoker IAM, ADMIN_A2A_URL → gateway
EDIT docs/USAGE.md                          document the [ADMIN] tools + confirm tokens + endpoint
NEW  tests/test_admin.py                    F1–F4 offline tests (InMemoryObjectStore + fake engine)
NEW  tests/test_admin_agent_routing.py      dispatch/round-trip (lifespan-wrapped, per to_a2a note)
```
