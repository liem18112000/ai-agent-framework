# non-ai.excalidraw — Caveman Explain

> ⚠️ Heads-up: the file `non-ai.excalidraw` is **empty** (no shapes drawn).
> So this report explains the **non-AI (human) version** of the testing flow —
> the twin of `full-flow.excalidraw`, but with the robot brains taken out.

---

## Ugg. Big idea.

**Full-flow = human + AI robot do test.**
**Non-AI = human do ALL test. No robot. Human brain only. Slow. Tired. But work.**

Same road. Same steps. Just no magic helper. Human do the digging, the thinking, the remembering.

---

## The hunt (steps, in order)

1. **Gather knowledge.** 🔍
   Human read Jira. Human read Confluence. Human dig code. Human read log.
   *(Robot version: agent auto-read + memory + code-graph. Human version: eyeball everything, by hand.)*

2. **Refine knowledge.** ❓
   Human confused? Human go ask other human. Ask BA. Ask dev. "What this mean?"
   *(Robot version: ask AI, AI answer. Human version: poke teammate.)*

3. **Define test plan.** 🗺️
   Human decide: How test? (API, screen, whole thing.) What test? (which feature.) What "pass" mean?
   *(Robot version: "reconfirm with AI". Human version: human decide alone.)*

4. **Say what "pass" mean.** 🎯
   Human write rule: this = good, this = bad. How much cover enough?

5. **Build test plan.** 🧱
   Human make fake data. Human write test case — happy path, angry path. Human write step 1, 2, 3.
   *(All by hand. No auto-generate.)*

6. **Run test.** 🏃
   Human set up machine. Human click / run test (by hand OR script). Human clean up mess. Human write down what happen.

7. **Big question: ALL TEST PASS?** ⚖️
   - **YES** ✅ → **Write completion report.** Document result. Close ticket. Hunt done. Eat. Sleep. 🦣
   - **NO** ❌ → go fix road (next).

8. **Fix road (when test fail):** 🔧
   - **Triage** — sort bug: tech problem or business problem?
   - **Raise defect ticket.** Write down history.
   - **Notify dev.** Poke dev. "You break. Fix."
   - **Dev fix bug.**
   - **Retest when fix done.** Loop back to step 6. 🔁

---

## What NON-AI is MISSING (the robot stuff)

- ❌ **No Polaris Memory Bank** — human no shared robot memory. Human forget. Human repeat mistake.
- ❌ **No Test / Ops / Report AI Agent** — no robot helper watch, report, or think.
- ❌ **No auto "collect insight"** — flow no learn by self. Only human learn (maybe).
- ❌ **No AI Q&A refine** — no smart robot to explain fast.

**Net:** same hunt, but human carry ALL rock. More slow. More miss. More tired. Robot help = less rock. 🪨

---

*Report by: caveman mode. Source: `full-flow.excalidraw` (the AI twin) minus all AI parts.*
