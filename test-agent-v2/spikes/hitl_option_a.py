"""A0 spike — Option A probe: LongRunningFunctionTool (HITL) inside a SequentialAgent.

Purpose: confirm/deny the reported resume bug (adk-python #3348/#5349/#3184/#5064 — "SequentialAgent
re-executes completed sub-agents after a LongRunningFunctionTool resume"). If clean on the pinned
ADK, Option A (idiomatic HITL tool) is an acceptable alternative to Option B; if not, Option B stays
the default.

REQUIRES A MODEL — the long-running tool is invoked by an LlmAgent, so this cannot run offline.
Set Vertex creds (GOOGLE_GENAI_USE_VERTEXAI=1 + GOOGLE_CLOUD_PROJECT/LOCATION, or GOOGLE_API_KEY)
and a model in MODEL below, then run. Without creds it prints SKIPPED and exits 0.

Probe shape: SequentialAgent([step_a, hitl, step_c]); step_a/step_c bump a counter in state each run.
  turn 1 → step_a runs once, hitl calls ask_human() → pending → pause.
  turn 2 → send the FunctionResponse for the long-running call → resume.
  CHECK: step_a's counter is still 1 (NOT re-executed) and step_c ran → clean. Else → bug present.
"""
from __future__ import annotations

import asyncio
import os
import sys

MODEL = os.environ.get("ADK_SPIKE_MODEL", "gemini-2.0-flash")  # or "vertex_ai/claude-sonnet-5" via LiteLlm


def _has_creds() -> bool:
    return bool(
        os.environ.get("GOOGLE_API_KEY")
        or (os.environ.get("GOOGLE_GENAI_USE_VERTEXAI") and os.environ.get("GOOGLE_CLOUD_PROJECT"))
    )


async def main() -> int:
    if not _has_creds():
        print("SKIPPED — Option A needs a model (LlmAgent drives the long-running tool). "
              "Set GOOGLE_API_KEY or Vertex creds + a MODEL, then re-run.")
        print("Decision unaffected: Option B is PROVEN (see hitl_option_b.py) and is the default. "
              "Option A would only be adopted if this probe comes back clean.")
        return 0

    from google.adk.agents import LlmAgent, SequentialAgent
    from google.adk.tools import LongRunningFunctionTool
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    def ask_human(question: str) -> dict:
        """Long-running: returns pending; a human supplies the answer out of band."""
        return {"status": "pending", "question": question}

    hitl = LlmAgent(
        name="hitl", model=MODEL,
        instruction="Call ask_human with a one-line question, then STOP and wait for the answer.",
        tools=[LongRunningFunctionTool(func=ask_human)],
    )
    # step_a / step_c bump a counter via output_key so re-execution is observable in state.
    step_a = LlmAgent(name="step_a", model=MODEL, instruction="Reply exactly 'A'.", output_key="a_ran")
    step_c = LlmAgent(name="step_c", model=MODEL, instruction="Reply exactly 'C'.", output_key="c_ran")
    root = SequentialAgent(name="seq", sub_agents=[step_a, hitl, step_c])

    svc = InMemorySessionService()
    await svc.create_session(app_name="a", user_id="u", session_id="s")
    runner = Runner(app_name="a", agent=root, session_service=svc)

    long_ids: list[str] = []
    print("--- turn 1 ---")
    async for ev in runner.run_async(user_id="u", session_id="s",
                                     new_message=types.Content(role="user", parts=[types.Part(text="begin")])):
        for lid in (getattr(ev, "long_running_tool_ids", None) or []):
            long_ids.append(lid)
        print("  ev:", ev.author, getattr(getattr(ev, "content", None), "parts", None))

    if not long_ids:
        print("PROBE INCONCLUSIVE — no long_running_tool_ids surfaced (model didn't call ask_human "
              "or API differs on this ADK). Inspect events above.")
        return 0

    # Resume: send the FunctionResponse for the long-running call.
    print("--- turn 2 (resume with human answer) ---")
    fr = types.Part(function_response=types.FunctionResponse(
        id=long_ids[0], name="ask_human", response={"status": "ok", "answer": "the human answer"}))
    async for ev in runner.run_async(user_id="u", session_id="s",
                                     new_message=types.Content(role="user", parts=[fr])):
        print("  ev:", ev.author, getattr(getattr(ev, "content", None), "parts", None))

    print("\nInspect: did step_a re-run on turn 2? If step_a appears again above => BUG present "
          "(#3348) => keep Option B. If only step_c ran => clean => Option A acceptable.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(f"\nPROBE ERRORED: {type(e).__name__}: {e}")
        sys.exit(2)
