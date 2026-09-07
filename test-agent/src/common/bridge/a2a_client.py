"""The A2A half of the A2A->MCP bridge.

Claude speaks MCP, not A2A. This module is a thin JSON-RPC 2.0 client (over httpx)
that drives the knowledge-gathering agent's `message/send` endpoint and normalizes
its two response shapes into one small result object:

  - a plain **Message** reply  (one-shot gather / read-helpers):  result.kind == "message",
    text in `result.parts[].text`;
  - a **Task**                 (multi-turn refine):               result.kind == "task",
    which may pause in `status.state == "input-required"`, text in
    `result.status.message.parts[].text`.

No `mcp` import lives here, so the translation logic is unit-testable without the MCP
runtime (see tests/test_bridge.py, which drives a real in-process agent over
httpx.ASGITransport).
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Self

import httpx

from common.models import (
    A2AResult,  # re-exported here for `from common.bridge.a2a_client import A2AResult`
)

_JSONRPC = "2.0"
_RPC_PATH = "/"  # a2a.utils.DEFAULT_RPC_URL
_CARD_PATH = "/.well-known/agent-card.json"


class A2AError(RuntimeError):
    """A JSON-RPC error returned by the agent (the `error` member was set)."""

    def __init__(self, code: Any, message: str, data: Any = None) -> None:
        super().__init__(f"A2A error {code}: {message}")
        self.code, self.data = code, data


def _text_parts(parts: list[dict] | None) -> list[str]:
    """Pull the text out of an A2A parts array (proto v0.3 JSON: {"kind":"text","text":...})."""
    out: list[str] = []
    for p in parts or []:
        t = p.get("text") if isinstance(p, dict) else None
        if isinstance(t, str) and t:
            out.append(t)
    return out


def extract_text(result: dict[str, Any]) -> str:
    """Collect every text part from a message- or task-shaped JSON-RPC result, in order."""
    if not isinstance(result, dict):
        return str(result)
    chunks: list[str] = []
    chunks += _text_parts(result.get("parts"))                       # plain Message
    chunks += _text_parts((result.get("status") or {}).get("message", {}).get("parts"))  # Task status
    for art in result.get("artifacts") or []:                        # Task artifacts
        chunks += _text_parts(art.get("parts"))
    if not chunks:                                                   # last resort: agent turns in history
        for h in result.get("history") or []:
            if h.get("role") == "agent":
                chunks += _text_parts(h.get("parts"))
    seen: set[str] = set()
    uniq = [c for c in chunks if not (c in seen or seen.add(c))]     # drop duplicates, keep order
    return "\n".join(uniq)


class A2ABridgeClient:
    """Minimal A2A client: `message/send` + agent-card fetch, with optional bearer auth.

    `transport` lets tests inject an httpx.ASGITransport wrapping the real agent app so the
    whole round-trip is exercised with no network; leave it None for real HTTP.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080/",
        token: str | None = None,
        *,
        timeout: float | None = None,
        transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # The detailed implement can run for minutes (serial batched Vertex calls); 180s errored
        # mid-call. Default 600s, tunable via A2A_CLIENT_TIMEOUT, so the bridge waits for the agent.
        if timeout is None:
            timeout = float(os.environ.get("A2A_CLIENT_TIMEOUT", "600"))
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.base_url = base_url
        self._http = httpx.AsyncClient(
            base_url=base_url, headers=headers, timeout=timeout, transport=transport
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def fetch_card(self) -> dict[str, Any]:
        r = await self._http.get(_CARD_PATH)
        r.raise_for_status()
        return r.json()

    async def send(
        self,
        text: str,
        *,
        context_id: str | None = None,
        task_id: str | None = None,
        message_id: str | None = None,
    ) -> A2AResult:
        """Send one text message; return the normalized reply.

        Pass `context_id` to keep a conversation together and `task_id` to answer a task the
        agent paused in `input-required`.
        """
        message: dict[str, Any] = {
            "messageId": message_id or uuid.uuid4().hex,
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
        }
        if context_id:
            message["contextId"] = context_id
        if task_id:
            message["taskId"] = task_id
        payload = {
            "jsonrpc": _JSONRPC,
            "id": 1,
            "method": "message/send",
            "params": {"message": message},
        }
        r = await self._http.post(_RPC_PATH, json=payload)
        r.raise_for_status()
        body = r.json()
        if body.get("error"):
            err = body["error"]
            raise A2AError(err.get("code"), err.get("message", ""), err.get("data"))
        result = body.get("result") or {}
        status = result.get("status") or {}
        return A2AResult(
            text=extract_text(result),
            context_id=result.get("contextId"),
            # a Message carries taskId at top level; a Task carries its id in `id`
            task_id=result.get("taskId") or result.get("id"),
            state=status.get("state"),
            kind=result.get("kind"),
            raw=result,
        )
