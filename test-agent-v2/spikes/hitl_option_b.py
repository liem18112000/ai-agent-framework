
    """A0 spike — Option B: custom BaseAgent that checkpoints HITL loop state into ADK session state.

Proves the recommended refine/define pattern for test-agent-v2:
  - a custom BaseAgent runs ONE interrogation round per invocation, writes its loop state via an
    Event `state_delta`, emits the question, and ENDS the invocation (pause);
  - the NEXT invocation on the same session reads the state back and advances to the next round
    (resume) — WITHOUT re-executing earlier rounds;
  - state survives a simulated process restart (we tear down the SessionService + Runner mid-run
    and rebuild them against the same on-disk SQLite DB before resuming).

No LLM is involved — the rounds are canned. A0 is about pause/resume *mechanics*, not the model.

Run:  test-agent-v2/.venv/Scripts/python.exe test-agent-v2/spikes/hitl_option_b.py
Exit code 0 + "SPIKE PASSED" => Option B is viable; make it the default for RefineAgent/DefineAgent.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

from google.adk.agents import BaseAgent
from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.genai import types

APP, USER, SID = "hitl_spike", "u1", "ctx-run-0001"
ROUNDS = ["business", "technical", "qa"]  # KGA refine rounds; TPD would be methodology/scope/metrics
DB = pathlib.Path(__file__).with_name(".spike_hitl.db")


def _last_user_text(ctx) -> str:
    for ev in reversed(getattr(ctx.session, "events", []) or []):
        c = getattr(ev, "content", None)
        if c and getattr(c, "role", None) == "user" and (c.parts or []):
            for p in c.parts:
                if getattr(p, "text", None):
                    return p.text
    return ""


class InterrogationSpikeAgent(BaseAgent):
    """Stateless agent — ALL loop state lives in session.state (so any instance can resume it)."""

    async def _run_async_impl(self, ctx):
        st = dict(ctx.session.state or {})
        answers = list(st.get("answers", []))
        awaiting = bool(st.get("awaiting", False))
        incoming = _last_user_text(ctx)

        # Continuation turn: the incoming text is the answer to the round we paused on.
        if awaiting and incoming and not st.get("done"):
            answers.append(incoming)

        answered = len(answers)
        if answered < len(ROUNDS):
            rnd = ROUNDS[answered]
            delta = {"answers": answers, "awaiting": True, "round_asked": rnd, "answered": answered}
            yield Event(
                author=self.name,
                content=types.Content(role="model", parts=[types.Part(text=f"ROUND={rnd} :: <question for {rnd}>")]),
                actions=EventActions(state_delta=delta),
            )
            return  # PAUSE — invocation ends here; next turn resumes from state

        # All rounds answered → finalize.
        delta = {"answers": answers, "awaiting": False, "done": True}
        yield Event(
            author=self.name,
            content=types.Content(role="model", parts=[types.Part(text=f"COMPLETE :: {len(answers)} answers :: {answers}")]),
            actions=EventActions(state_delta=delta),
        )


def _svc() -> DatabaseSessionService:
    # ADK 2.x uses create_async_engine → needs an ASYNC driver. sqlite → aiosqlite;
    # prod Cloud SQL Postgres → postgresql+asyncpg (same asyncpg the v1 stack already uses).
    return DatabaseSessionService(db_url=f"sqlite+aiosqlite:///{DB.as_posix()}")


async def _turn(runner: Runner, text: str) -> str:
    out = []
    async for ev in runner.run_async(
        user_id=USER, session_id=SID,
        new_message=types.Content(role="user", parts=[types.Part(text=text)]),
    ):
        c = getattr(ev, "content", None)
        for p in (getattr(c, "parts", None) or []):
            if getattr(p, "text", None) and getattr(c, "role", None) != "user":
                out.append(p.text)
    return " | ".join(out)


async def main() -> int:
    if DB.exists():
        DB.unlink()
    agent = InterrogationSpikeAgent(name="interrogator")

    # --- start: create the session + first round ---
    svc = _svc()
    await svc.create_session(app_name=APP, user_id=USER, session_id=SID)
    runner = Runner(app_name=APP, agent=agent, session_service=svc)
    t1 = await _turn(runner, "start")
    print("T1 (start)          ->", t1)

    # --- SIMULATED RESTART: throw away the service + runner, rebuild from the same sqlite file ---
    del runner, svc
    svc = _svc()
    runner = Runner(app_name=APP, agent=agent, session_service=svc)
    reloaded = await svc.get_session(app_name=APP, user_id=USER, session_id=SID)
    print("state after restart ->", dict(reloaded.state))

    t2 = await _turn(runner, "biz: QR default on, individual only")
    print("T2 (biz answer)     ->", t2)
    t3 = await _turn(runner, "tech: failCount = day-of-month")
    print("T3 (tech answer)    ->", t3)
    t4 = await _turn(runner, "qa: cover boundary + negative + error")
    print("T4 (qa answer)      ->", t4)

    final = await svc.get_session(app_name=APP, user_id=USER, session_id=SID)
    print("final state         ->", dict(final.state))

    # --- assertions ---
    asked = [x.split("ROUND=")[1].split(" ")[0] for x in (t1, t2, t3) if "ROUND=" in x]
    ok = True

    def check(cond, label):
        nonlocal ok
        print(("  PASS " if cond else "  FAIL ") + label)
        ok = ok and cond

    check(asked == ROUNDS, f"3 rounds asked in order, once each: {asked}")
    check("business" in t1, "T1 asked the FIRST round (business)")
    check(dict(reloaded.state).get("awaiting") is True, "state persisted across restart (awaiting=True)")
    check("COMPLETE" in t4, "T4 finalized (COMPLETE)")
    check(len(final.state.get("answers", [])) == 3, "3 answers accumulated")
    check(final.state.get("done") is True, "session marked done")
    # no round re-asked on the finalize turn:
    check("ROUND=" not in t4, "no round re-executed on resume/finalize")

    print("\n" + ("SPIKE PASSED — Option B viable" if ok else "SPIKE FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception as e:  # noqa: BLE001 — spike: surface the full failure to fix the API call
        import traceback
        traceback.print_exc()
        print(f"\nSPIKE ERRORED: {type(e).__name__}: {e}")
        sys.exit(2)
