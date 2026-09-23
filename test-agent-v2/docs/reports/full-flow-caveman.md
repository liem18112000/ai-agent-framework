# full-flow.excalidraw — Caveman Explain

**Big idea: robot AND human hunt test together. Human throw rock, robot help,
robot remember, robot learn. Same hunt as before — but this the **v2** rock, so
every robot-poke now ride through the ONE gateway door.** 🦣🤖🚪

*(Names now v2-current. Pipeline no change.)*

---

## The hunt (steps, left to right)

Rock say **"We start here."** 👉

1. **Gather knowledge.** 🔍
   Read Jira. Read Confluence. Robot memory + code-graph + log. Grab all rock.

2. **Refine knowledge.** ❓
   Robot ask human question. Human answer. Human say "robot, you understand right?"

3. **Make test plan.** 🗺️ *(reconfirm with robot)*
   Decide: How test? (API, E2E, UI.) What test? (which feature.) What "pass" mean?
   Side rock → **Test Evaluation define**: what count as pass? how much cover enough?

4. **Build test plan.** 🧱
   Make fake data + fake account. Write case — happy path, angry path. Step 1, 2, 3.

5. **Run test.** 🏃 on machine (local, dev…)
   Set up machine. Run case (hand OR auto). Clean mess. Write down what happen.
   Side rock → **Test Evaluation support**: watch how test run.

---

## BIG QUESTION rock: ALL TEST PASS? ⚖️

- **YES** ✅ → **Write completion report.** 🎉 Sort result. Close ticket. Eat mammoth. 🍖
- **NO** ❌ → go **fix road** (below).

### Fix road (test fail) 🔧
- **Triage** — sort bug: tech problem or business problem?
- **Triage support** — raise defect ticket. Write history.
- **Send ticket → poke dev (notify/trigger) → dev FIX BUG** (+ fix support) **→ retest when fix → LOOP back.** 🔁

---

## The robot helpers 🤖 (down + side)

- **Test AI Robot**, **Ops AI Robot** (watch/monitor), **Report AI Robot** (make report). Three robot help hunt.
- **After AI → collect insight → loop.** Robot LEARN after hunt. Get smart. Loop back. 🧠
- **Polaris Memory Bank** — big shared robot brain (the `kga-v2-memory` book). All robot read + write. Robot no forget. 🗄️
- **v2 twist:** every tool-poke (gather · refine · define · implement · evaluate) go
  through the ONE **`mcp-gateway-v2`** door, then A2A to the right robot. One door, same hunt. 🚪

---

## Two special rock at bottom 🪨

**① `test-evaluation-agent-v2` — ALREADY BUILT (Step 5).** ✅
Extra rock that CHECK the knowledge pack quality: did robot grab right stuff? leak wrong stuff?
→ give **Pack Quality Score (PQS)**. Just look, never block. Run AFTER gather, BEFORE plan.

**② Two-Tier Memory (CQRS) — BUILT M0–M6 · LIVE (klara-nonprod).** ✅
Make robot brain smarter — find by MEANING not just word-match.
- **GCS** = big truth book (append-only, never lie). 📖
- **Cloud SQL + pgvector** = fast recall brain (vector 768 + text search); reuses `kga-v2-taskstore`. ⚡
- Read both way, mix, pick best, keep de-bias. Flip switch `MEMORY_BACKEND`. Postgres die? → fall back to GCS book. Hunt never break. 🛡️
- More detail rock: `two-tier-agent-memory-pgvector.*`.

---

## Rock color meaning 🎨

- 🔵 **blue** = normal step (gather, refine, build, run, report)
- 🟣 **purple** = robot-brain step (plan, implement, eval define) + AI-agent helper
- 🔴 **red** = BAD path (triage, fix bug)
- 🟢 **green** = GOOD (eval support / Ops robot)
- 🟡 **yellow** = start rock / memory bank
- 🩵 **cyan** + 🟠 **amber** = the two special bottom rock (quality check + new brain plan)

---

## One grunt takeaway

**full-flow v2 = same test hunt, robot on every step.**
Robot help, robot remember in `kga-v2-memory` brain, robot learn after.
One robot (quality check, now `test-evaluation-agent-v2`) already built ✅. Smarter brain (pgvector) still just plan 📐.
**New in v2: all robot reached through the single `mcp-gateway-v2` door.** 🪨👍

*(Twin of `non-ai.excalidraw` — that one no robot, this one full robot.)*
