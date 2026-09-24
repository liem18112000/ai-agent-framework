# exec-overview.excalidraw — Caveman Explain

**Big idea: TPD robot write hunt-plan on leaf (`.feature`), but NOBODY RUN IT — leaf just
sit there. NEW 4th robot (EXEC) grab the leaf, RUN it for real against a chosen cave
(environment), WATCH what happen with real eyes (oracles), FIX flaky step (human say yes),
SORT each fail (bug? heal? flaky? env?), write every run to the stone ledger, then hand the
real numbers to the score-robot (TEV) so it stop GUESSING.** 🦣▶️🧪

**Status: BUILT — 4th robot (EXEC) LIVE on the gateway (5 tools, real run via 3 engines,
OpenAPI oracle, triage+heal, 2 ledger tables). Leaner than the survey — MEASURE signals
(coverage/flakiness/mutation), differential mode, most JEV sites, and the whole TEV feed
still DREAMED, not built.** ✅+⏸️

---

## ⓪ THE GAP — leaf never run 🍂✗ (red dashed box, top-left)

Before EXEC, the hunt-chain go `gather → refine → define → implement_plan → get_scenarios`
and **STOP**. `implement_plan` carve scenarios "for the execution stage" — and that stage
did not exist. Nothing ran, nothing self-fixed, every downstream quality number was a GUESS
(a *proxy*). **EXEC now CLOSE that gap — it grab the scenarios and RUN them for real.** ✅
*(But the score-robot don't drink the real numbers yet — the TEV feed still DREAMED, see ⑥.)*

---

## ① THE NEW ROBOT — EXEC, same shape as the other three 🟧 (big orange box)

EXEC is the **4th A2A agent**, brother of KGA / TPD / TEV, keyed by the same `context_id`,
registered on the same MCP gateway. **No new datastore, no new protocol** — it reuse every
seam already there. Two rules keep it safe:
- **Off the request path.** A full run is heavy (heavier than the three Vertex calls that
  once tripped `ERROR_TIMEOUT`). So `run_suite` is **chunked / polled / resumable** — KICK
  OFF, say `in_progress`, client re-poll — same multi-turn dance `implement_plan` already
  do. Five tools total: `run_suite` · `triage_run` · `heal_step` · `get_run_report` ·
  `list_environments`. 🕒
- **Deterministic first, robot only to heal.** Each scenario routes to the engine that fits
  its `methodology` (ApiEngine deterministic, BrowserEngine / LlmEngine translate NL once
  via the LLM) → big-brain wake up again only to HEAL a break. 🧊

---

## ② THE INNER LOOP — run → measure → (heal) → triage 🔁 (blue/green/yellow boxes)

One `run_suite(context_id, env)` call drive a small bounded loop, checkpointed to GCS so a
Cloud Run kill **resume**, not restart:

- **0 · RESOLVE ENV** 🔵 — pick the target cave by NAME from the `EXEC_ENVIRONMENTS`
  env-map (NOT a JEV Choice — that site still dreamed), health-probe the `base_url`, upsert
  its row.
- **1 · RUN** 🔵 (`EXEC_RUNNER`: `stub` default, `auto` = real) — **3 real engines routed
  by scenario `methodology`**: **ApiEngine** (httpx conformance) · **BrowserEngine** (real
  Playwright chromium + an LLM NL→browser-plan translator) · **LlmEngine** (LLM NL→request).
  NOT Playwright+behave, NOT Playwright-MCP. *(The run is the ONLY place holding live creds —
  the trust boundary, see ⚠️.)*
- **2 · MEASURE** 🟢 (on PASS) — **BUILT: home-grown OpenAPI conformance** (status +
  jsonschema response-schema, NOT Schemathesis). *(NOT YET — robot still dream coverage-delta,
  flakiness ×5, and mutation kills.)*
- **3 · TRIAGE** 🟡 (on FAIL) — sort the fail: **Actual Bug** → record + stop 🔴 ·
  **UI change** → HEAL · **Flaky/Env** → quarantine ⬜. Heuristic + a JEV-fronted `choice`
  cascade, **default OFF** (`TPD_DECISION_BACKEND`). BUILT.
- **HEAL step** 🟠 — LLM propose-and-verify patch, surfaced through the client's **human
  Yes/No gate** — *never a silent retarget* (a silent one hide a real regression). BUILT.
- **4 · PERSIST + REPORT** 🟢 — heavy rocks → GCS; one run row → Postgres. BUILT.

---

## The stone ledger 🪨 (green + grey boxes, bottom-left)

- **Shared Cloud SQL** (`common.db.get_engine`) — the SAME Postgres that already holds the
  task store + ADK sessions + pgvector. EXEC add **TWO new tables** (both **text PKs**, an
  `exec_run.status` column): `exec_environment` (one row per cave ever tested — name,
  base_url, revision, `creds_ref` = the auth KIND only, never a secret value) and `exec_run`
  (one row per run — summary, signals, triage, `trace_uri`). **Reuse the Postgres — no new
  datastore** (a redeploy once wiped loose GCS state; the ledger must survive). BUILT. 🟢
- **GCS** ⬜ — the heavy rocks (run.json, traces, heal patches) + a `trace_uri` pointer.
  Same GCS-heavy / SQL-light split the rest of the system use.

---

## Many caves — 2nd cave IS the oracle 🗺️ (light-blue strip, bottom)

EXEC run the SAME leaf across **many named caves** from `EXEC_ENVIRONMENTS`: `dev` ·
`staging` · `rev:abc123` (a Cloud Run revision) · `tenant:42`, each with its own auth
(bearer / bearer_fetch / login via `auth.py`). New cave → new row, on first sight. **(NOT
YET — robot still dream differential mode:** ≥2 caves, diff the answers, consensus-as-oracle.
The store shape is there; the diff is not.) 🔀

---

## JEV — fast typed brain in front of big-brain 🟣 (purple box, right)

EXEC decisions are typed judgments — exactly what the **JEV `DecisionProvider`** port is for
(`choice` · `score` · `noul`, ~150ms, ~free). The cascade: JEV answer first; conf ≥ θ →
typed verdict; else fall through to the existing LLM judge. `TPD_DECISION_BACKEND` unset →
JEV returns None and every caller keep its LLM path → worst case = today. **Default OFF.**
**Only ONE site is wired: Triage.** *(NOT YET — robot still dream JEV at heal-accept,
flakiness, and env-selection.)* 🧠⚡

---

## ⑥ FEED THE SCORE-ROBOT — retire the guesses 🟢 (green box, bottom-right) — NOT YET

**This whole box is still a DREAM.** EXEC *persist* `exec_run.signals` today, but the
score-robot (TEV) does NOT read them yet. The plan: hand back REAL mutation score →
`fault_detection` 0.30, **executed** coverage delta → `coverage` 0.20, + conformance +
flakiness — TPS weights unchanged, only the INPUTS get real. But there is **no
`evaluate_run` tool, no `metrics/execution.py`, no `fault_detection` source-swap** built. The
signals sit in the ledger waiting for a reader. *(robot still dream this whole feed.)* ⏸️

---

## ⚠️ SAFETY — this robot hold the KEYS 🔒 (red dashed sandbox)

Unlike read-only KGA/TPD/TEV, EXEC **hold test-env creds and drive live systems** — the
biggest security delta in the whole cave. Guard it (BUILT): secrets are a **reference** (a
named env var, Secret-Manager-injected), **never the value** in Postgres or GCS — the ledger
stores `creds_ref` = the auth KIND only · a per-run **origin allow-list** pins egress to the
run's `base_url` scheme+host+port (NOT `common/net.host_blocked` — EXEC legitimately hits
internal/localhost test caves) · file-upload bytes are an **inline base64 bank fixture** (via
`data_ref`), never a filesystem path. This is the primary review surface. 🛡️

---

## Rock color meaning 🎨

- 🟧 **orange** = the NEW EXEC robot + the run flow / heal path
- 🔵 **blue** = deterministic run steps (resolve · run) · 🟢 **green** = real signals /
  measure / persist / the ledger / TEV
- 🟡 **yellow** = the triage decision · ⬜ **grey** = GCS · flaky-quarantine
- 🟣 **purple** = JEV typed brain · 🔴 **red** = the gap / actual-bug / 🔒 the run trust boundary
- 🟦 **light-blue dashed** = the many caves. *(NOTE: the diagram's DESIGN-ONLY dashing is now
  stale — the backbone is BUILT; only MEASURE-signals, differential, the extra JEV sites, and
  the TEV feed remain dreamed.)*

---

## One grunt takeaway

**Leaf finally RUN — for real. 4th robot (EXEC) grab the scenarios, run them through 3 real
engines (httpx · Playwright · LLM) against a NAMED cave, judge API responses with a
home-grown OpenAPI oracle, sort each fail (triage, JEV-fronted default OFF), human-approve
each heal, and write every cave + run to the shared stone (2 new tables, text PKs).** Off the
hunt-path, resumable, human owns the gate, keys are references not values, egress pinned to
the cave. **Leaner than the survey: no coverage/flakiness/mutation signals, no differential
mode, JEV only on triage, and the score-robot don't read the run yet — those still DREAMED.**
✅🦣

*(Sibling rocks: `exec-architecture` / `exec-flow` / `exec-multienv-db` / `exec-jev-cascade`
/ `exec-tev-extension` = the six section diagrams this one summarizes;
`agentic-qa-assured-loop` = the generation loop whose MEASURE step this run finally closes.)*
