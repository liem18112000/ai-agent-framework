"""RouterAgent — our agent base and the single seam over the ADK agent framework.

Every deterministic router in this repo inherits from `RouterAgent` (not `google.adk.agents.BaseAgent`
directly) and reaches the turn's text / reply event through `self.read()` / `self.reply()` rather than
importing `common.adk.events`. So the dependency on the agent framework is confined to THIS module and
`common/adk/events.py` — swapping ADK for another library is a change to those two files, not to every
agent. `build()` is the self-factory each module's `build_root_agent()` delegates to.
"""

from __future__ import annotations

from google.adk.agents import BaseAgent

from common.adk.events import incoming_text, text_event

Agent = BaseAgent
"""Neutral alias for a heterogeneous sub-agent (gather/refine/define/implement) — lets concrete
routers annotate their sub-agent fields without importing the framework class directly."""


class RouterAgent(BaseAgent):
    """Base for the deterministic, no-LLM text routers. Inherits the ADK agent so ADK's Runner /
    `to_a2a` can still drive it, while giving our code one place to depend on and one place to swap.

    Concrete agents override `_run_async_impl` and yield `self.reply(...)` (or delegate to a sub-agent's
    `run_async`); they never import the framework's agent class or event helpers directly.
    """

    @staticmethod
    def read(ctx) -> str:
        """The current turn's inbound user text (hides the framework's context shape)."""
        return incoming_text(ctx)

    def reply(self, text: str):
        """One text-reply event authored by this agent (hides the framework's Event type)."""
        return text_event(self.name, text)
