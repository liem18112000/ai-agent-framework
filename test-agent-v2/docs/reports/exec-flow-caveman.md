# exec-flow.excalidraw — Caveman Explain

**Big idea: ONE call, `run_suite(context_id, env)`, drive a small bounded loop —
pick-cave → RUN → if PASS measure & write, if FAIL sort-the-fail → maybe heal (human say
yes) → re-run the patched step, bounded, and loop. Every scenario checkpointed so a kill
RESUMES, not restarts.** 🦣🔁

**Status: BUILT (leaner). RUN=3 engines by methodology · TRIAGE+HEAL wired · REPORT wired. DEFERRED: MEASURE (coverage·flakiness×5·mutation), JEV-Choice env-pick, TEV feed.** ✅

---

## ⓪ START — one call kicks it off 🟠 (orange box, top)

`run_suite(context_id, env)` — the client fire it and re-poll (multi-turn, off the request
path). Everything below happen inside that one bounded loop.

---

## ① PICK THE CAVE then RUN 🔵 (dark-blue boxes)

- **0 · RESOLVE ENV** — pick the target cave (**JEV Choice §5**), **health-probe
  `base_url`**, **upsert the env row (§4)**.
- **1 · RUN (deterministic)** — **3 engines routed by `methodology`** (api·httpx / browser·Playwright / llm-translate); OpenAPI-grounded. Discover a step ONCE, freeze it — big-brain sleep until a step break.

The run then branch two ways ↓

---

## ② PASS → MEASURE → write it down 🟢🔵 (green + blue boxes, left)

- **PASS** (green arrow) → **2 · MEASURE** 🟢 — coverage delta · flakiness ×5 ·
  schema/status/auth conformance · mutation kills · per-scenario oracle.
- → **4 · PERSIST** 🔵 — `run.json`+traces → **GCS**; run row + oracle results → **Postgres (§4)**.
- → **5 · REPORT** 🟢 — `get_run_report`; **real signals → TEV (§6)** + the human.

---

## ③ FAIL → TRIAGE → sort the fail 🟡 (yellow diamond, right)

- **FAIL** (red arrow) → **3 · TRIAGE** (yellow diamond) — **JEV Choice → LLM**, sort into
  three buckets:
  - **Actual Bug** 🔴 → *record + stop* (a real bug is not something to heal around).
  - **UI change** 🟣 → `heal_step()` → **HUMAN Yes/No gate** 🔴 (*never a silent
    retarget* — a silent one would hide a real regression).
  - **Flaky / Env** 🔵 → *quarantine ×5* (still run, no longer block).

---

## The loop-back 🔁 (purple dashed arrow, wraps left)

An accepted heal → **re-run patched step, bounded by MAX_HEALS** (purple dashed arrow all
the way back up to **1 · RUN**). Exhaust the budget → record unresolved and move on, never
spin. Each done scenario is checkpointed → a Cloud Run kill **resumes** at the last one.

---

## Rock color meaning 🎨

- 🟠 **orange** = the `run_suite` entry point
- 🔵 **dark-blue** = deterministic steps (resolve · run) · **light-blue** = persist / flaky-quarantine
- 🟢 **green** = measure · report (real signals) · green PASS arrow
- 🟡 **yellow diamond** = the TRIAGE decision · 🔴 **red** = FAIL arrow · actual-bug · the human gate
- 🟣 **purple** = the heal path (UI-change → heal_step) · **purple dashed** = the bounded re-run loop-back

---

## One grunt takeaway

**One call, one bounded loop: pick cave → run deterministic → PASS measure+write, FAIL sort
→ (human-approved) heal → re-run bounded → loop. Checkpoint every scenario so a kill picks
up where it fell.** Bug stops, flaky quarantines, only UI-change heals — and always with the
human holding the gate. **BUILT (leaner) — MEASURE signals + JEV-Choice env-pick still to come.** 🔁🦣

*(Sibling rocks: `exec-architecture` = where this loop lives · `exec-jev-cascade` = the JEV
brain behind the triage/heal/flaky/env calls · `exec-overview` = the whole picture.)*
