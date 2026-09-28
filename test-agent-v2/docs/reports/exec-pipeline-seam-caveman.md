# exec-pipeline-seam.excalidraw — Caveman Explain

**Big idea: the old hunt-chain go straight and human-gated, then STOP at `get_scenarios`.
EXEC bolt on AFTER it — one orange arrow drops down to a new run-stage — optional and
read-model-friendly, EXACTLY like `evaluate_plan`. The outside stay linear and human-gated;
the run-loop lives on the inside.** 🦣➡️⤵️

**Status: BUILT — the seam is live: run_suite → [triage_run / heal_step] → get_run_report after get_scenarios. (evaluate_plan execution-grounding still deferred.)** ✅

---

## ① THE OLD CHAIN — straight, human-gated 🔵🟡 (top row)

Left-to-right, the pipeline already there (KGA · TPD · TEV):
`gather → refine → approve → [evaluate_pack] → define_plan → approve_plan → implement_plan
→ get_scenarios`.
- 🔵 **blue** = the work steps (gather / refine / define_plan / implement_plan / get_scenarios).
- 🟡 **yellow** = the **human gates** (`approve` · `approve_plan`) — human hold the spear.
- 🟦 **dashed light-blue** = `[evaluate_pack]` — an **optional read-only** gate.

The chain end at `get_scenarios` — and today, that's it. Leaf sits unrun.

---

## ② THE ORANGE DROP — EXEC clips in AFTER 🟠 (the connector)

From `get_scenarios` an **orange connector** curves down and left into a **new stage** —
*"EXEC slots in AFTER get_scenarios (optional, read-model-friendly like evaluate_plan)."* It
does NOT rewrite the chain; it hang off the end. 🟠

---

## ③ THE NEW RUN-STAGE 🟧 (bottom row, orange boxes)

`run_suite → [triage_run / heal_step] → get_run_report → [evaluate_plan *]`
- 🟧 **orange** = the NEW EXEC tools (`run_suite` · the optional `[triage_run/heal_step]` ·
  `get_run_report`).
- 🟦 **dashed light-blue** = `[evaluate_plan *]` — re-enter TEV, now **execution-grounded**
  (`*` = the §6 upgrade: real signals feed the score).

The orange bracket underneath reads *"EXEC — the NEW A2A agent (run → [triage/heal] →
report)."*

---

## The key idea 🔑

**Optional + read-model-friendly.** Like `evaluate_plan`, the run-stage is a *read model*
bolted on the side — you can skip it and the pipeline still works; run it and TEV's numbers
get real. The human-gated linear spine never changes shape.

---

## Rock color meaning 🎨

- 🔵 **blue** = existing work steps · 🟡 **yellow** = human gates (approve / approve_plan)
- 🟦 **dashed light-blue** = optional read-only stages (`[evaluate_pack]` · `[evaluate_plan *]`)
- 🟧 **orange** = the NEW EXEC stage + the orange connector dropping in after `get_scenarios`

---

## One grunt takeaway

**EXEC does not rewrite the chain — it clips on AFTER `get_scenarios` with one orange arrow,
optional and read-model-friendly like `evaluate_plan`, then loops back into an
execution-grounded `evaluate_plan`.** Outside stay straight and human-gated; the run-loop
hides inside. **The seam is BUILT; only its evaluate_plan execution-grounding (§6) is still to come.** 🧩

*(Sibling rocks: `exec-flow` = what `run_suite` does once you're in the new stage ·
`exec-tev-extension` = why the re-entry `evaluate_plan *` is now execution-grounded ·
`exec-overview` = the whole picture.)*
