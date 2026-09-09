# agentic-qa-assured-loop.excalidraw — Caveman Explain

**Big idea: one big LLM call NOT enough. Robot make many test, RUN them for real,
MEASURE, then keep ONLY the test that help. If test break, robot self-heal and re-run.
Loop small, loop cheap, human still say final Yes/No.** 🔁🧪✅

*(This the v2 doc set. Concept same as v1 — this the plan that replaces the single
`implement_plan` call. Names kept current.)*

---

## The hunt line — GENERATE → EXECUTE → MEASURE → GATE 🟢🟠🔵🔴

Left to right, top row, this the loop body:
- **1 GENERATE** (green) — make ensemble of K test with Vertex / Claude. Start from the Insight Pack.
- **2 EXECUTE** (orange) — RUN the test for real: Playwright · behave · Schemathesis (API).
- **3 MEASURE** (blue) — coverage · flake x5 · mutation · schema. Did the test earn its keep?
- **4 GATE** (red) — keep test ONLY if: it builds + passes x5 + raises coverage. No help → throw away.
- **6 JUDGE** (purple) — LLM-as-judge give rubric score → **Approved .feature + quality report**.

## Side rocks — self-heal + oracles 🩹🔮

- **Self-Heal locator** (orange dashed) — test break on run? agentic / Healenium fix the locator, then **re-run**. No cry, just heal.
- **ORACLES** (blue dashed) — how MEASURE knows right from wrong: schema/status/auth · metamorphic · differential (API) · visual-AI (UI).

## The learn-back — REFLECT 🧠

- **5 REFLECT** (purple band, top) — write *"why it failed"* into the Memory Bank, feed the failure **back into GENERATE**. Next make-test smarter. Rejected candidates loop back up.

## The cave-wall — SHARED MEMORY BANK 📖

Big green band at bottom, **per context_id**, persists after EVERY step:
candidate scenarios · execution traces · healed locators · coverage/mutation/judge scores · reflections.
So if Cloud Run instance get evicted, it **resumes** — not restart from zero.

## Rock color meaning 🎨

- 🟢 **green** = GENERATE · approved output · the shared Memory Bank
- 🟠 **orange** = EXECUTE (solid) · Self-Heal locator (dashed)
- 🔵 **blue** = MEASURE (solid) · ORACLES (dashed)
- 🔴 **red** = the GATE (keep-only-if-it-helps)
- 🟣 **purple** = JUDGE · REFLECT band · Human Yes/No gate
- ⬜ **slate** = the Insight Pack + Codegraph input

## One grunt takeaway

**Make many → RUN for real → measure → keep only what helps → heal the broken → reflect → loop.**
Loop is bounded (max_iterations + token budget) and **exactly ONE LLM call per iteration**
(so no serial-Vertex Cloud Run timeout). Robot stop guessing test are good — robot PROVE it.
Human still owns the final Yes/No. 🦣👍
