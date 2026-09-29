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

from google.adk.agents import LlmAgent

from common.env import env_float
from common.llm import meter
from common.monitoring import get_logger

log = get_logger("llm.adk")

_DEFAULT_GEN_TIMEOUT_S = 180.0


def _gen_timeout_s() -> float:
    """Per-call ceiling (s) for one generator run (env ``TPD_GEN_TIMEOUT_S``). Bounds a slow Vertex
    call so it degrades to the caller's heuristic instead of hanging the handler past the server's
    request ceiling — the root cause of implement_plan timing out with nothing persisted."""
    return max(1.0, env_float("TPD_GEN_TIMEOUT_S", _DEFAULT_GEN_TIMEOUT_S))


def _record_usage(label: str, seen: list) -> None:
    """Meter the ADK path's token spend. ADK reports google.genai `usage_metadata` (not Anthropic's
    `usage`), so the field names differ; `cached_content_token_count` is the cache READ — the LiteLlm
    bridge exposes no cache-write count, so a cached ADK prefix shows reads with no matching write.

    Takes the LAST usage seen, not the sum: ADK re-emits cumulative usage on partial and final events,
    so summing double-counts. Our generators are single-call leaves, so the last event is the total."""
    if not seen:
        return
    u = seen[-1]
    meter.record(label,
                 input=getattr(u, "prompt_token_count", 0) or 0,
                 output=getattr(u, "candidates_token_count", 0) or 0,
                 cache_read=getattr(u, "cached_content_token_count", 0) or 0)


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


async def run_json_agent(agent: LlmAgent, *, output_key: str, user: str = "generate",
                         state: dict | None = None) -> dict | None:
    """Run ``agent`` once in a throwaway Runner with ``user`` as the turn; return the validated dict.

    ``state`` seeds the throwaway session's ``session.state`` — needed by agents whose
    ``InstructionProvider`` reads a state key (e.g. the KGA planners read ``PLAN_INPUT_KEY``); ``None``
    leaves it empty (the TPD generators pass their whole task as ``user``, so they don't need it).

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
    await svc.create_session(app_name="tpd-gen", user_id="tpd", session_id="gen", state=state or {})
    runner = Runner(app_name="tpd-gen", agent=agent, session_service=svc)

    texts: list[str] = []  # capture the model's raw output for the state-empty recovery path
    usage = []              # last non-None usage_metadata — see _record_usage

    async def _drive() -> None:
        async for ev in runner.run_async(user_id="tpd", session_id="gen", new_message=types.Content(
                role="user", parts=[types.Part(text=user)])):
            if (u := getattr(ev, "usage_metadata", None)) is not None:
                usage.append(u)
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

    _record_usage(agent.name, usage)
    session = await svc.get_session(app_name="tpd-gen", user_id="tpd", session_id="gen")
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
