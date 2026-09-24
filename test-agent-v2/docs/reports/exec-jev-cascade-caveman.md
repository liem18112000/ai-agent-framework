# exec-jev-cascade.excalidraw — Caveman Explain

**Big idea: EXEC make a stream of tiny yes/no/which decisions (bug or UI change? accept this
heal? is it flaky? which cave?). A fast typed brain (JEV) answer first — ~150ms, near-free.
If it's confident enough, take its typed verdict (~90% of the time). If not, fall through to
the old big-brain LLM judge, code UNCHANGED (~10% hard tail). JEV FRONTS the LLM, never
replaces it — strictly additive, default OFF.** 🦣🧠⚡

**Status: PARTIAL — only the Triage site is wired (runner.triage → DecisionProvider.choice, default OFF, degrades to the heuristic). Heal-accept / flakiness / env-selection are DEFERRED.** ◑

---

## ① STATE IN → fast brain 🔵🟢 (blue ellipse → green box)

- **runtime state (trace / envs)** 🔵 (dark-blue ellipse = the input) flows into…
- **JEV DecisionProvider** 🟢 — three primitives: **`choice` / `score` / `noul`**,
  **~150ms, ~free**. It gives back a typed `Verdict(value, probs, confidence)`. 🟢

---

## ② THE GATE — confident enough? 🟡 (yellow diamond)

- **`confidence ≥ THRESHOLD ?`** (yellow decision diamond).
  - **yes (~90%)** → green arrow → **typed Verdict (value, probs, confidence)** 🟢 — the
    fast typed path, done.
  - **no (~10% hard tail)** → purple arrow down → **existing LLM judge (unchanged code)** 🟣
    → purple arrow back up into the SAME typed Verdict.

**JEV fronts, LLM finishes.** The 10% hard cases still get the full big-brain; the 90% easy
ones skip it. Strictly additive: worst case = today. ⚖️

---

## ③ WHERE IT LANDS IN EXEC 🔵→🟢 (blue boxes → green labels, bottom-left)

*"Executor decision sites → typed, not free LLM calls":*
- **Triage** (Bug/Heal/Flaky/Env) → **Choice / Noul**
- **Heal-accept** (`'patch preserves intent'`) → **Noul**
- **Flakiness** (`'non-deterministic'`) → **Noul + history**
- **Env selection / run-health** → **Choice / Score**

Each blue site used to be a *free-form LLM call*; JEV turn it into a *typed* call.

---

## The safety line 🛡️ (grey footer)

*"`TPD_DECISION_BACKEND` unset → `get_decision_provider()`=None → every caller keeps its LLM
path. I8: deterministic scorers stay JEV-free."* So JEV is **default OFF**, and it only
touch **runtime judgments** — never the deterministic product path (`evaluate_pack` /
`evaluate_plan` / `metrics/*`). Calibrate the threshold on TEV goldens before trusting the
fast path.

---

## Rock color meaning 🎨

- 🔵 **dark-blue** = the runtime-state input (ellipse) · the decision-site boxes
- 🟢 **green** = JEV DecisionProvider · the typed Verdict · the "yes ~90%" arrow · the "→ Choice/Noul" labels
- 🟡 **yellow diamond** = the confidence gate (≥ THRESHOLD?)
- 🟣 **purple** = the "no ~10% hard tail" fall-through to the unchanged LLM judge (+ its arrows)
- ⬜ **grey** = the default-OFF / I8 safety footer

---

## One grunt takeaway

**Tiny typed brain answers first (~150ms, ~free); if confident (~90%) take its verdict, else
fall through to the unchanged LLM (~10%). It FRONTS the LLM, never replaces it — default OFF,
deterministic scorers untouched (I8).** Triage · heal-accept · flakiness · env-pick all
become typed calls instead of free-form LLM calls. **Wired for EXEC only on paper.** 🧠⚡

*(Sibling rocks: `exec-flow` = the triage/heal/flaky/env sites that call this cascade ·
`jev-concept` / `jev-v2-architecture` = the JEV backend itself · `exec-overview` = the whole picture.)*
