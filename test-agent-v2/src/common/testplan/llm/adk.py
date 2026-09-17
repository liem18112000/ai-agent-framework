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
import itertools
import os

from google.adk.agents import LlmAgent

from common.monitoring import get_logger

log = get_logger("llm.adk")

_DEFAULT_GEN_TIMEOUT_S = 180.0

# Unique per-run ADK app/session ids (Phase A): concurrent batches must NOT share ADK session state.
# Each call already gets its own InMemorySessionService, but reusing app/session/output ids across
# concurrent runs risks collisions in any id-keyed ADK global (tracing, registries) — give each run a
# distinct id. GIL makes next() atomic enough for asyncio.
_RUN_SEQ = itertools.count()


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

    uid = str(next(_RUN_SEQ))  # unique per call so concurrent batches never share ADK ids
    app, sess = f"tpd-gen-{uid}", f"gen-{uid}"
    svc = InMemorySessionService()
    await svc.create_session(app_name=app, user_id="tpd", session_id=sess)
    runner = Runner(app_name=app, agent=agent, session_service=svc)

    texts: list[str] = []  # capture the model's raw output for the state-empty recovery path

    async def _drive() -> None:
        async for ev in runner.run_async(user_id="tpd", session_id=sess, new_message=types.Content(
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

    session = await svc.get_session(app_name=app, user_id="tpd", session_id=sess)
    data = (session.state or {}).get(output_key) if session else None
    # Return state only if it has real content. On the deployed Claude/LiteLlm path ADK populates the
    # state with a DEFAULT-constructed schema (e.g. ``{"items": []}``) when it can't parse the model's
    # fenced JSON — truthy but EMPTY — so ``if data`` alone returned that and skipped recovery.
    if isinstance(data, dict) and any(data.values()):
        return data
    if data and not isinstance(data, dict):
        return data
    recovered = loads_obj("\n".join(texts))  # state empty/default → parse the model's fenced/prefaced JSON
    if recovered is None:
        log.warning("%s: no structured state and raw text unparseable (%d chars) → heuristic",
                    agent.name, len("\n".join(texts)))
    else:
        # Log the SHAPE (not the content) — a recovered-but-empty payload is otherwise invisible: the
        # caller just reports "batch empty/invalid" and degrades, with no way to tell an empty `items`
        # from a wrong-dict pick by `loads_obj`. Keys + per-key length is enough to tell those apart.
        shape = {k: (len(v) if isinstance(v, (list, str, dict)) else v) for k, v in recovered.items()}
        log.info("%s: recovered structured output from raw model text (ADK state was empty); "
                 "raw=%d chars, shape=%s", agent.name, len("\n".join(texts)), shape)
    return recovered
