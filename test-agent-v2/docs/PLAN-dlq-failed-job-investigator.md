# PLAN — DLQ failed-job investigator (LLM post-mortem → `failed_job_report` → knowledge base)

**Goal.** Turn dead-lettered scenario-generation jobs from discarded noise into knowledge. A DLQ consumer
runs a **Vertex LLM post-mortem** on each failed job, persists a **`failed_job_report`** DB row (the original
job + the failure reason + the LLM diagnosis), and feeds a **reusable lesson** into the existing knowledge
base so future runs can recall "this kind of job failed for this reason".

This closes the gap flagged for Phase C: today the DLQ topic has no subscriber, so dead-lettered data is
dropped (a Pub/Sub topic with no subscription discards messages), and the pipeline only recovers via the
coordinator's per-batch heuristic fallback. This plan makes the failure *learnable*.

---

## Grounding — what already exists (reuse, don't rebuild)
- **DLQ substrate (Phase C):** `implement/generate/workers.py` (coordinator + `handle_job`, which raises on
  failure → nack → redeliver → dead-letter after 5), `worker.py` (Starlette **push** endpoint — the sibling a
  DLQ consumer mirrors), `pubsub.tf` (topic + DLQ topic `tpd-gen-batches-dlq`, **no DLQ subscriber yet**).
- **Lessons = `Insight`** (`common/models/refine.py`) with `kind ∈ {lesson, correction, gotcha}` — there is no
  separate lesson type. **GCS `MemoryBank` is the record of truth**; pgvector is a downstream projection.
- **Capture path:** `learn.enqueue(bank, CaptureJob(context_id, run_id, step, signals=[dict]))`
  (`common/learn/queue.py`) → `learn.drain` → `capture_lessons` (`common/learn/capture.py`): distils
  `LessonSignal`s, **drops ungrounded ones** (a `source_ref` must be a node in the index graph), dedupes,
  `bank.upsert_insight` → GCS → `on_write` → pgvector `IndexJob`. Governed by `veto_lesson` /
  `search_lessons` (`govern.py`), recalled by `recall_lessons` (`recall.py`, B4/B5 de-bias). Flags default OFF
  (`TPD_CAPTURE_LESSONS`).
- **DB:** async SQLAlchemy, `common/db.py::get_engine()` (or `None` when unconfigured). Tables are **raw
  `CREATE TABLE IF NOT EXISTS` applied lazily** — no ORM, no migrations. Cleanest template =
  `common/prompts/stores.py` (a `_DDL` tuple + `for ddl: await conn.execute(text(ddl))` on the shared engine).
- **Investigator model:** `common/adk/model.py::complete(prompt, *, max_tokens, cache_prefix, tier)` +
  `common/llm/parse.loads_obj` — the worker-proven path (no ADK Runner). `tier="fast"` for a cheap diagnosis.

---

## The crux — where the failure reason comes from
Pub/Sub dead-letter delivery carries the **original message** + attributes (`CloudPubSubDeadLetterSource…`,
incl. delivery count) but **NOT the subscriber's exception**. So the reason must be captured at failure time:

**D1 — the worker writes an error breadcrumb (chosen).** `handle_job`, on failure (before it raises→nacks),
writes `workers/<ctx>/<run>/<batch>.error.json` to GCS = `{error, traceback_head, attempt_ts}`. The DLQ
consumer reads the original job (from the dead-letter message) + this breadcrumb. *Rejected: re-run the job to
reproduce* — a poison job just re-fails and doubles cost. If a hard crash (OOM) skips the breadcrumb, the
consumer degrades to "reason: unknown (delivery_count=N)" from the Pub/Sub attributes.

---

## Flow
```
generation worker fails ─(writes <batch>.error.json)─▶ nack ─5×─▶ tpd-gen-batches-dlq (topic)
        │
        ▼  (NEW) DLQ push subscription → POST /dlq on the worker service
  DLQ consumer:  decode original job  +  read error breadcrumb  +  read delivery_count (attrs)
        │
        ├─▶ INVESTIGATOR: complete(investigate_prompt(job, error), tier="fast") → loads_obj
        │        → { category, root_cause, severity, suggested_fix, lesson_statement }
        │
        ├─▶ persist  failed_job_report  row  (original job + reason + diagnosis)
        │
        └─▶ learn.enqueue(bank, CaptureJob(signals=[{statement: lesson, kind:"gotcha",
                 source_refs:[<ctx pack ref>], confidence:"low", rationale}]))  → KB lesson (grounded, de-biased)
        ▼
      return 204 (ack — the failure is now recorded, don't redeliver)
```

## `failed_job_report` schema (new `common/failjob/store.py`, raw-DDL lazy table à la prompts/stores.py)
| Column | Type | Notes |
|---|---|---|
| `id` | text PK | `failjob:{ctx}:{batch}:{sha1(error)[:10]}` (idempotent — redelivery upserts) |
| `context_id` | text | the run |
| `batch_id` | int | which batch/units |
| `image_sha` | text | the deployed version that failed (drift-aware) |
| `created_at` | timestamptz | |
| `delivery_count` | int | from the dead-letter attributes |
| `failure_reason` | text | the breadcrumb error (or "unknown") |
| `original_job` | jsonb | the full job: `{system, user, unit_ids, result_blob, max_tokens}` |
| `category` | text | fixed taxonomy: `schema_invalid \| timeout \| quota \| oversize \| refusal \| transport \| unknown` |
| `severity` | text | `low \| medium \| high` |
| `root_cause` | text | the LLM diagnosis |
| `suggested_fix` | text | actionable |
| `lesson_statement` | text | the one-sentence reusable lesson |
| `lesson_id` | text null | the captured `Insight` id once it lands in the KB |
| `investigation` | jsonb | raw LLM output, for audit |

Store API (async, mirrors `PgPromptStore`): `ensure()` (lazy DDL), `upsert_report(row)`, `list_reports(limit, category=)`,
`get_report(id)`. `get_engine() is None` → no-op (in-memory/gcs deployments just skip persistence, log instead).

## Investigator (prompt + model)
`complete(investigate_prompt(job, failure_reason, delivery_count), max_tokens=1500, tier="fast")` → `loads_obj`.
The prompt supplies: the original user prompt (truncated), `unit_ids`, the error + `traceback_head`,
`delivery_count`; asks for STRICT JSON `{category (from the taxonomy), root_cause, severity, suggested_fix,
lesson}` where `lesson` is one imperative sentence usable by a future run. `tier="fast"` is fine (short
diagnosis; well under the 64000 fast-model cap). Best-effort: if `loads_obj` returns nothing, store the report
with `category="unknown"` + the raw failure — never lose the record.

## Knowledge-base integration (reuse `learn`, respect the de-bias)
- The lesson is a **`gotcha` `Insight`**, enqueued via the existing `learn.enqueue` → `capture_lessons` pipeline
  (distill → ground → `upsert_insight` → GCS → pgvector). No parallel lesson system.
- **It must pass the grounding gate** (`_grounded` drops signals whose `source_refs` aren't index nodes) — so
  the signal's `source_refs` = a real node for the run (the context's pack/plan node). Otherwise it's silently
  dropped.
- **De-bias:** captured at `confidence="low"`; recall already applies B4/B5 (IDF hub-penalty + structural
  grounding), and it's vettable via `veto_lesson`. A failure-lesson is a *recallable hint*, never auto-applied —
  this is the same memory-bias discipline the B-phases fought.

---

## Files & wiring
- **`common/failjob/store.py`** (new) — the `failed_job_report` table DDL + async store (mirror `prompts/stores.py`).
- **`common/failjob/investigate.py`** (new) — `investigate_prompt(...)` + `run_investigation(job, reason, count) → dict`
  (the `complete()`+`loads_obj` call; best-effort, never raises).
- **`test_plan_definition/implement/generate/workers.py`** — `handle_job` writes the `<batch>.error.json`
  breadcrumb on failure (before raising).
- **`worker.py`** — add `POST /dlq` route: decode the dead-letter message → read breadcrumb → investigate →
  `upsert_report` → `learn.enqueue` the lesson → 204. Reuses the existing worker service (no new service).
- **`deployments/.../pubsub.tf`** — a DLQ **push subscription** `tpd-gen-batches-dlq-sub` → `<worker>/dlq`, with
  `message_retention_duration` (so the data is retained — the topic-drops-without-subscription gotcha), OIDC
  auth (runtime SA), and its own small `max_delivery_attempts` so a failing *consumer* doesn't loop forever
  (drop after N — the report is best-effort). All under `var.deploy_workers`.
- **Admin surface (optional):** an admin tool `list_failed_jobs` over `list_reports` for operator review.

## Gating & safety
- **`TPD_DLQ_INVESTIGATE=1`** (code) + `deploy_workers=true` (infra); default OFF → no consumer, no table use.
- Everything best-effort: a failed investigation / DB-down / KB-enqueue error still **acks** and logs — the DLQ
  consumer never blocks or loops. Correctness of generation is unaffected (the coordinator already heuristic-fills).
- **Privacy/retention:** `original_job` + the report carry ticket content (the pack). Bound DLQ + DB retention;
  lock down `failed_job_report` access; consider truncating/omitting the raw prompt if not needed for diagnosis.

## Decisions
- **D1** breadcrumb over re-run (above). **D2** raw-DDL lazy table (no ORM/migrations). **D3** investigator =
  `complete()`+`loads_obj`, fast tier. **D4** lesson via existing `learn.enqueue` as a grounded low-confidence
  `gotcha`, subject to B4/B5 recall + veto. **D5** consumer = a `/dlq` route on the existing worker service
  (reuse, no new service). **D6** ack-after-record + a consumer-side delivery cap so the DLQ consumer can't loop.

## Rollout
1. Worker error breadcrumb + `failed_job_report` table + store (unit-test the DDL/row round-trip + id-keying).
2. Investigator (`investigate.py`) — unit-test `investigate_prompt` + `loads_obj` parsing of a canned diagnosis.
3. `/dlq` route wiring (mirror `worker.py`'s push handler; unit-test the envelope decode + best-effort path).
4. Lesson enqueue integration (grounded `gotcha`) + veto/admin surface.
5. TF: DLQ push subscription + retention + IAM; live-validate end-to-end (force a batch failure → DLQ →
   report row + KB lesson).

## Caveats
- Not offline-testable end-to-end (Pub/Sub + Cloud Run); the pure parts (schema round-trip, prompt build,
  diagnosis parse, envelope decode) are.
- The breadcrumb depends on the worker surviving long enough to write it; a hard OOM/crash yields
  "reason: unknown" + delivery_count only — still a report, just shallower.
- The lesson-bias risk is real; the low-confidence + grounding + B4/B5 recall + veto path is the mitigation,
  not elimination. Watch that failure-lessons don't skew generation; veto aggressively if they do.
