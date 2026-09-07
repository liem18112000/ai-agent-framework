"""BridgeSession — the per-bridge A2A client + multi-turn task state, shared by both MCP servers.

Both agents' bridges are identical except for their tool set + MCPServer name/instructions. The
plumbing each tool needs — a lazily-built A2ABridgeClient, the context_id -> task_id map for
multi-turn interrogation, the send/error wrapper, the "continue-or-restart a turn" step, and the
agent-card fetch/format — lives here so each mcp_server only declares its tools.
"""

from __future__ import annotations

import httpx

from common.bridge.a2a_client import A2ABridgeClient, A2AError, A2AResult


class BridgeSession:
    """Holds the A2A client + task map for one bridge process (single stdio client, one loop)."""

    def __init__(self, base_url: str, token: str | None) -> None:
        self.base_url = base_url
        self.token = token
        # context_id -> task_id: multi-turn interrogation pauses a Task in `input-required`
        # and the client must answer on the same task; MCP tool calls are otherwise independent.
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
            return await self.get_client().send(text, **kw)
        except A2AError as exc:
            raise RuntimeError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Cannot reach the A2A agent at {self.base_url}: {exc}") from exc

    async def turn(self, context_id: str, answer: str | None, start_text: str) -> A2AResult:
        """One multi-turn interrogation step: continue the live task if answering, else (re)start.

        Tracks context_id -> task_id and clears it when the agent reports the task completed.
        """
        task_id = self.tasks.get(context_id)
        if answer is not None and task_id:
            res = await self.ask(answer, context_id=context_id, task_id=task_id)
        else:  # start (or restart) the interrogation
            res = await self.ask(start_text, context_id=context_id)
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
