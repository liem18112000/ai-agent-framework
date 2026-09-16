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

import asyncio
import contextlib
import os

from google.adk.agents import LlmAgent

from common.monitoring import get_logger

log = get_logger("llm.adk")

_DEFAULT_GEN_TIMEOUT_S = 180.0


def _gen_timeout_s() -> float:
    """Per-call ceiling (s) for one generator run (env ``TPD_GEN_TIMEOUT_S``). Bounds a slow Vertex
    call so it degrades to the caller's heuristic instead of hanging the handler past the server's
    request ceiling — the root cause of implement_plan timing out with nothing persisted."""
    with contextlib.suppress(KeyError, ValueError, TypeError):
        return max(1.0, float(os.environ["TPD_GEN_TIMEOUT_S"]))
    return _DEFAULT_GEN_TIMEOUT_S


def build_generator_agent(*, name: str, system: str, output_schema, output_key: str, model):
    """A structured-output leaf ``LlmAgent`` for one generator (model via the provider, I8).

    ``system`` is the leaf's **instruction** — the shared, stable context pack. It is sent verbatim
    (via the ``InstructionProvider`` closure, so literal ``{…}`` braces pass through) and, on the
    LiteLlm/Vertex path, **prompt-cached** (see the provider's cache_control injection). The
    per-generator TASK is the *user* message (``run_json_agent(..., user=…)``), so the pack stays a
    stable cacheable prefix reused across generators + assured reflect-rounds."""
    return LlmAgent(name=name, model=model, output_schema=output_schema, output_key=output_key,
                    instruction=lambda _ctx: system, disallow_transfer_to_parent=True,
                    disallow_transfer_to_peers=True)


async def run_json_agent(agent: LlmAgent, *, output_key: str, user: str = "generate") -> dict | None:
    """Run ``agent`` once in a throwaway Runner with ``user`` as the turn; return the validated dict.

    ADK's ``output_schema`` LlmAgent is meant to populate ``session.state[output_key]``, but the
    deployed Claude-on-Vertex (LiteLlm) path leaves it EMPTY — Claude fences/prefaces its JSON and
    ADK's strict parser rejects it (no exception, no state), so every generator silently degraded to
    heuristic (the ~0.1-score prod bug the offline fakes couldn't reproduce, since a fake yields clean
    JSON that ADK parses fine). So we ALSO capture the model's text and, when state is empty, parse the
    JSON out of it ourselves (``loads_obj`` tolerates fences + prose) — a robust recovery path."""
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    from common.llm.parse import loads_obj

    svc = InMemorySessionService()
    await svc.create_session(app_name="tpd-gen", user_id="tpd", session_id="gen")
    runner = Runner(app_name="tpd-gen", agent=agent, session_service=svc)

    texts: list[str] = []  # capture the model's raw output for the state-empty recovery path

    async def _drive() -> None:
        async for ev in runner.run_async(user_id="tpd", session_id="gen", new_message=types.Content(
                role="user", parts=[types.Part(text=user)])):
            for part in (getattr(getattr(ev, "content", None), "parts", None) or []):
                if getattr(part, "text", None):
                    texts.append(part.text)

    timeout = _gen_timeout_s()
    try:
        await asyncio.wait_for(_drive(), timeout=timeout)
    except TimeoutError:  # slow Vertex call → bounded → degrade to heuristic (never hang the handler)
        log.warning("%s: generator timed out after %.0fs; falling back to heuristic", agent.name, timeout)
        return None
    except Exception as exc:  # noqa: BLE001 — ADK schema-validation etc.; try the raw-text recovery below
        log.warning("%s: generator run raised (%s); trying raw-text recovery", agent.name, exc)

    session = await svc.get_session(app_name="tpd-gen", user_id="tpd", session_id="gen")
    data = (session.state or {}).get(output_key) if session else None
    if data:
        return data
    recovered = loads_obj("\n".join(texts))  # state empty → parse the model's fenced/prefaced JSON
    if recovered is None:
        log.warning("%s: no structured state and raw text unparseable (%d chars) → heuristic",
                    agent.name, len("\n".join(texts)))
    else:
        log.info("%s: recovered structured output from raw model text (ADK state was empty)", agent.name)
    return recovered
