# exec-tev-extension.excalidraw — Caveman Explain

**Big idea: the score-robot (TEV) grade the test plan TODAY without ever running it — so its
biggest number, `fault_detection`, is fed by GUESSES (proxies). EXEC run the tests for real
and hand back REAL signals — mutants actually KILLED, coverage actually HIT. Same TPS
weights, same 0.30 slot — only the INPUT changes from guess to run.** 🦣📊➡️✅

**Status: DESIGNED, NOT BUILT — the executor persists real per-run signals to exec_run today, but TEV does not read them yet (no evaluate_run, no metrics/execution.py, no fault_detection swap).** ⏸️

---

## ① TODAY — proxies, no run 🟦 (blue DASHED boxes, left)

Dashed = *inactive guess*. TEV score without running:
- **`metrics/oracle.py :: oracle_strength`** — "deterministic proxy for mutation" (grade the
  `expected` string, run nothing).
- **`metrics/mutation.py :: fault_class_coverage`** — "PROXY (real mutation gated on
  execution)" — count if a fault was *aimed at*, not *killed*.
- both feed → **`fault_detection = 0.30` (fed by proxies)**.

The dashed border is the tell: these numbers are placeholders WAITING for a real run. 🟦

---

## The divider ┊ (dashed vertical line)

Left = what runs today (guesses). Right = what EXEC unlocks (real). Same weight slot on both
sides — that's the whole argument.

---

## ② WITH THE EXECUTOR — real signals ✅ (green SOLID boxes, right)

Solid green = *real, active*. EXEC feed four real signals:
- **real mutation score (mutmut / PIT / Stryker)** — mutants **KILLED**, not aimed-at.
- **executed coverage delta** — lines/branches **actually hit**.
- **schema/status/auth conformance pass-rate** (from the home-grown OpenAPI oracle — the one MEASURE signal already built).
- **flakiness ×5 from the run ledger**.

→ they feed → **`fault_detection = 0.30` (same weight, REAL input)** 🟢, sourced from **Test
Executor `exec_run.signals`** 🟠 (orange box feeding up).
Plus *"+ new TEV tool `evaluate_run(context_id)` · benchmark across environments."*

---

## ③ THE FORMULA DON'T CHANGE 🔵 (blue band, bottom)

**`TPS = 0.30·fault_detection + 0.25·brief_groundedness + 0.20·coverage +
0.15·oracle_strength + 0.10·trajectory`** — *"formula unchanged — only `fault_detection`'s
source improves (proxy → real run)."* Same weights, same shape; TEV keep its deterministic,
LLM-free spine (I8). Only the provenance of the heaviest term gets real. 🔵

---

## Rock color meaning 🎨

- 🟦 **blue DASHED** = TODAY's inactive proxy metrics (oracle_strength · fault_class_coverage · proxy-fed fault_detection)
- ┊ **dashed vertical line** = the today-vs-with-executor divider
- 🟢 **green SOLID** = the real execution signals + the real-input `fault_detection`
- 🟠 **orange** = the source: Test Executor `exec_run.signals`
- 🔵 **blue band** = the TPS formula (unchanged) + the "benchmark across environments" note

---

## One grunt takeaway

**TEV's heaviest number is a guess today because nothing runs; EXEC runs it and swaps the
guess for a real one — mutants KILLED, coverage HIT, conformance + flakiness measured — same
0.30 weight, same TPS formula, better input.** New tool `evaluate_run(context_id)`; the
assured loop's MEASURE step finally gates on a run, not a proxy. **The right half is a dream
until EXEC is built.** 📊✅

*(Sibling rocks: `exec-multienv-db` = where `exec_run.signals` is stored ·
`tpd-evaluation-adk-testsuite` = the TPS/TEV scoring this upgrades · `exec-overview` = the
whole picture.)*
