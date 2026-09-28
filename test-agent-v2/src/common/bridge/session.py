"""BridgeSession — the per-bridge A2A client + multi-turn task state, shared by both MCP servers."""

from __future__ import annotations

import httpx

from common.bridge.a2a_client import A2ABridgeClient, A2AError, A2AResult


class BridgeSession:
    """Holds the A2A client + task map for one bridge process (single stdio client, one loop)."""

    def __init__(self, base_url: str, token: str | None) -> None:
        self.base_url = base_url
        self.token = token
        self.tasks: dict[str, str] = {}
        self._client: A2ABridgeClient | None = None

    def get_client(self) -> A2ABridgeClient:
        if self._client is None:
            self._client = A2ABridgeClient(self.base_url, self.token)
        return self._client

    def set_client(self, client: A2ABridgeClient | None) -> None:
        """Inject a client (tests point this at an in-process agent); resets session state."""
        self._client = client
        self.tasks.clear()

    async def ask(self, text: str, **kw: str | None) -> A2AResult:
        try:
            res = await self.get_client().send(text, **kw)
        except A2AError as exc:
            raise RuntimeError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Cannot reach the A2A agent at {self.base_url}: {exc}") from exc
        if res.state == "failed":
            # A failed A2A task otherwise returns as success with (often) empty text — the "malformed /
            # empty response" symptom. Surface it as an error so every read-only tool routing through
            # `ask` (and `turn` for refine/define_plan/implement_plan) fails loudly instead of silently.
            raise RuntimeError(res.text or "agent task failed with no detail")
        return res

    async def turn(self, context_id: str, answer: str | None, start_text: str) -> A2AResult:
        """One multi-turn interrogation step: send the answer when answering, else (re)start.

        Routing is by `answer is not None`, NOT by a live A2A task_id: our interrogation agents finish
        their invocation every round (so `to_a2a` reports state="completed" each turn and the task_id
        would be dropped), yet they rehydrate their own per-round state from the bank keyed on
        `context_id`. Gating on task_id here silently re-sent `start_text` and DISCARDED the human's
        answer — the round advanced but nothing was ingested. The context_id is the durable thread."""
        text = answer if answer is not None else start_text
        res = await self.ask(text, context_id=context_id, task_id=self.tasks.get(context_id))
        if res.task_id:
            self.tasks[context_id] = res.task_id
        if res.state == "completed":
            self.tasks.pop(context_id, None)
        return res

    async def card(self) -> str:
        """Fetch the agent's A2A card and format its name, version, and skills."""
        try:
            card = await self.get_client().fetch_card()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Cannot reach the A2A agent at {self.base_url}: {exc}") from exc
        skills = ", ".join(s.get("id", "?") for s in card.get("skills", []))
        return f"{card.get('name')} v{card.get('version')}\nskills: {skills}"
