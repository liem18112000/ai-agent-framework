"""Run a TPD generator ``LlmAgent`` to a validated structured dict (offline-safe).

The implement generators (scenarios / test-data / steps) are ADK ``LlmAgent``s with a pydantic
``output_schema`` — a structured-reply leaf (no tools, no transfer). We drive each one through a
throwaway in-process ``Runner`` and read the validated dict back from ``session.state[output_key]``
(§5.5: read state, do not parse event text). The prompt is passed as an ``InstructionProvider``
closure — a callable ``instruction`` bypasses ADK ``{key}`` state-templating, so the prompts' literal
JSON braces (``{id, title, ...}``) pass through verbatim. On invalid model output ADK raises inside
``run_async`` while validating against the schema; we catch it and return ``None`` so the caller can
degrade to its heuristic (the best-effort contract — never raise).
"""

from __future__ import annotations

from google.adk.agents import LlmAgent

from test_plan_definition.monitoring import get_logger

log = get_logger("llm.adk")


def build_generator_agent(*, name: str, prompt: str, output_schema, output_key: str, model):
    """A structured-output leaf ``LlmAgent`` for one generator (model via the provider, I8)."""
    return LlmAgent(
        name=name,
        model=model,
        output_schema=output_schema,
        output_key=output_key,
        instruction=lambda _ctx: prompt,
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )


async def run_json_agent(agent: LlmAgent, *, output_key: str) -> dict | None:
    """Run ``agent`` once in a throwaway Runner; return ``state[output_key]`` (dict) or ``None``."""
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    svc = InMemorySessionService()
    await svc.create_session(app_name="tpd-gen", user_id="tpd", session_id="gen")
    runner = Runner(app_name="tpd-gen", agent=agent, session_service=svc)
    try:
        async for _ in runner.run_async(
            user_id="tpd", session_id="gen",
            new_message=types.Content(role="user", parts=[types.Part(text="generate")]),
        ):
            pass
    except Exception as exc:  # noqa: BLE001 — invalid/empty output degrades to heuristic, never raises
        log.warning("%s: generator run failed (%s); falling back to heuristic", agent.name, exc)
        return None
    session = await svc.get_session(app_name="tpd-gen", user_id="tpd", session_id="gen")
    return (session.state or {}).get(output_key) if session else None
