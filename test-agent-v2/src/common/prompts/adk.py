"""The ADK adapter (P0) — the ONLY module here that imports ADK.

We do not invent a loading mechanism. ADK already accepts a late-bound instruction:

    InstructionProvider = Callable[[ReadonlyContext], str | Awaitable[str]]

and ``LlmAgent.canonical_instruction(ctx)`` awaits the result if it is awaitable. So the adapter's job
is only to produce that callable from a ``PromptStore`` entry — nothing in the ADK call path changes.

One ADK behaviour drives the engine split: passing a CALLABLE sets ``bypass_state_injection=True``,
so ADK skips its own ``{var}`` templating on the result. That is load-bearing for us (our bodies are
full of literal braces), which is why ``engine="none"`` renders here via ``$``-substitution. A template
that genuinely wants session-state substitution opts in with ``engine="state"``, and we then call
ADK's own ``inject_session_state`` — the pattern ADK documents for exactly this case.
"""

from __future__ import annotations

from collections.abc import Mapping

from common.prompts.port import JINJA2, NONE, PromptStore


def instruction_from(store: PromptStore, key: str, *, params: Mapping[str, object] | None = None,
                     version: int | None = None):
    """Adapt a stored prompt into an ADK ``InstructionProvider``."""

    async def _provider(ctx) -> str:
        tpl = store.get(key, version=version)
        if tpl.engine == NONE:
            return tpl.render(params)
        from google.adk.utils.instructions_utils import inject_session_state

        return await inject_session_state(tpl.body, ctx, use_jinja2=(tpl.engine == JINJA2))

    return _provider


def static_provider(text: str):
    """The degenerate provider: a constant string, as a callable.

    This is what ``build_generator_agent`` passed before the store existed, kept as a named function so
    the "literal braces must survive, therefore never a raw str" decision has one place to live."""

    def _provider(_ctx) -> str:
        return text

    return _provider
