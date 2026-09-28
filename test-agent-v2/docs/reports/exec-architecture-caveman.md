# exec-architecture.excalidraw — Caveman Explain

**Big idea: the new run-robot (EXEC) is the SAME SHAPE as the three robots already in the
cave. Same gateway door, same shared stone-store, same `context_id` key. Only ONE thing new
— EXEC keep a locked Run Sandbox off to the side that holds the cave keys and drive live
systems. No new door, no new store, no new tongue.** 🦣🏛️➕

**Status: BUILT — EXEC is the LIVE 4th A2A agent behind the same gateway, same
`context_id`, same shared Cloud SQL (2 new tables). Only the surveyed heavy tooling
(behave / Schemathesis / Playwright-MCP) was NOT what shipped — see ③.** ✅

---

## ① ONE DOOR — the client talk MCP to the gateway 🚪 (blue boxes, top)

- **Claude Code client** (light-blue) **owns the Yes/No gates** — the human still hold the
  spear. It talk **MCP** down to…
- **MCP Gateway** (dark-blue) — **one endpoint fronts all 4 A2A agents.** Same door the
  three robots already use; EXEC just register behind it too. 🔵

---

## ② FOUR ROBOTS — three old, one NEW 🧍🧍🧍🦺 (blue + orange boxes)

Under the gateway hang four brothers, all keyed by the same `context_id`:
- **KGA** (knowledge gathering) · **TPD** (test-plan definition) · **TEV** (test
  evaluation) — the three old blue robots, all **read-only**.
- **EXEC** (execution + self-heal) 🟠 — **the NEW one.** Register EXACTLY like the others:
  `EXEC_A2A_URL` + `register_exec()`. Orange = new + it hold keys (not read-only like the blue three).

---

## ③ THE SANDBOX — the one robot that hold keys 🔒 (red/pink box)

EXEC does NOT run tests inside itself. It **kick off + poll** a separate **Run Sandbox**
(pink box, red stroke) — **OFF the request path** (a full run is heavy; doing it inline
would trip the Cloud Run timeout, same lesson as the serial Vertex calls). Inside the
sandbox: **Playwright · httpx · an LLM translator · a home-grown OpenAPI conformance oracle** (NOT behave/Schemathesis/Playwright-MCP), plus the **test-env creds + controlled
egress** — *a distinct trust boundary* no read-only robot ever crossed. 🔴

---

## ④ SHARED STONE-STORE — reuse everything 🪨 (green + blue boxes, bottom)

The sandbox **persist run/env** down into the SAME state every robot shares (keyed by
`context_id`):
- **Cloud SQL** (`common.db`) 🟢 — task store · sessions · pgvector already live here; EXEC
  add **env registry + run rows (NEW)**. Green = the new bit.
- **GCS** 🔵 — `run.json` · traces · heal patches.
- **graphify codegraph** 🔵 — producer/consumer + focal targets for the run.

*"Shared state (context_id) — reused by all agents"* is the whole point: EXEC add tables,
not a datastore.

---

## Rock color meaning 🎨

- 🔵 **light-blue** = client / old blue robots / GCS / codegraph · **dark-blue** = the one MCP gateway
- 🟠 **orange** = the NEW EXEC robot (+ orange labels: `EXEC_A2A_URL` · `register_exec()` · "kicks off + polls, OFF request path")
- 🔴 **red/pink** = the Run Sandbox = the new trust boundary (creds + egress)
- 🟢 **green** = Cloud SQL with the NEW env-registry + run rows · green arrows = "persist run/env"

---

## One grunt takeaway

**EXEC is brother number four — same gateway door, same `context_id`, same shared
stone-store — the ONLY new thing is a locked sandbox holding the cave keys and driving live
systems, off the request path.** No new plumbing; that is why it's cheap to add. **But it's
BUILT (leaner than the survey). 🦺🔒

*(Sibling rocks: `exec-flow` = what happens INSIDE run_suite · `exec-multienv-db` = the two
new Cloud SQL tables · `exec-overview` = the whole picture on one rock.)*
