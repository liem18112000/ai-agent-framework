# A0 spike — HITL pause/resume on ADK (findings)

De-risks the one real unknown before any bulk porting: can a multi-round human-in-the-loop
interrogation (refine/define) pause and resume cleanly on ADK? See
[`../docs/IMPLEMENTATION-PLAN.md`](../docs/IMPLEMENTATION-PLAN.md) §4 A0.

## Run

```bash
test-agent-v2/.venv/Scripts/python.exe test-agent-v2/spikes/hitl_option_b.py   # proven, offline
test-agent-v2/.venv/Scripts/python.exe test-agent-v2/spikes/hitl_option_a.py   # skips w/o a model
```

## Result — ✅ Option B is viable; adopt it as the default

`hitl_option_b.py` **PASSED** all 7 checks: a custom `BaseAgent` runs one round per invocation,
checkpoints loop state via an Event `state_delta`, emits the round, and ends the invocation; the next
invocation reads state back and advances. Three rounds paused/resumed in order, **state survived a
simulated restart** (the `DatabaseSessionService` + `Runner` were torn down and rebuilt from the
on-disk SQLite file mid-run), and **no round re-executed**.

`hitl_option_a.py` (LongRunningFunctionTool inside a SequentialAgent — the shape with the reported
resume bugs) **needs a model** to trigger the tool call, so it is model-gated and was **not** run
offline. It is ready to run later with Vertex/API creds. The decision does not depend on it: Option B
is proven and safe, so it is the default. Option A would only be adopted if that probe comes back clean.

## Confirmed ADK facts (env: `google-adk 2.8.0`, python 3.12)

> The plan was written against `>=1.22`; the pin resolves to **2.x** today. Retarget version-sensitive
> notes to **2.x** (the substrate below is verified on 2.8.0).

- **Version:** `google-adk` installs as **2.8.0** — ADK has moved to 2.x. Update the `>=1.22` pin.
- **`DatabaseSessionService` needs the `[db]` extra** (`pip install "google-adk[db]"` → sqlalchemy)
  **and an async driver**: it calls `create_async_engine`, so the URL must use an async dialect —
  `sqlite+aiosqlite:///…` for the spike; **`postgresql+asyncpg://…`** in prod (the same asyncpg the
  v1 stack already uses in `common/db.py`). A plain `sqlite:///` / `postgresql://` URL fails.
- **State persistence:** mutating `ctx.session.state` in a custom agent is **not** enough — persist by
  yielding `Event(actions=EventActions(state_delta={...}))`; the Runner applies it via the
  SessionService. This is the load-bearing pattern for the checkpoint.
- **Custom agent:** subclass `BaseAgent`, implement `async def _run_async_impl(self, ctx)` and
  `yield Event(...)`. Keep it **stateless** (no pydantic instance fields) — all loop state lives in
  session state, so any instance can resume any session.
- **Session API is async:** `await session_service.create_session(...)` / `get_session(...)`;
  drive turns with `runner.run_async(user_id=, session_id=, new_message=types.Content(...))`.
- Reading the turn's input inside the agent: scan `ctx.session.events` for the latest `role=="user"`
  text part.

## Impact on the plan

- **RefineAgent / DefineAgent → Option B** (custom `BaseAgent` + session-state checkpoint), as the
  `common/adk/interrogation.py` skeleton already sketches — now empirically validated.
- `common/adk/services.py` must build the session service with `postgresql+asyncpg://` and depend on
  `google-adk[db]`.
- Retarget `[verify @1.22]` → `[verify @2.x]` across the docs; re-check `to_a2a`, `LiteLlm`, and the
  eval-metric APIs against 2.8.0 during A.0/B.
