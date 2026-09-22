"""The A2A half of the A2A->MCP bridge."""

from __future__ import annotations

import os
import uuid
from typing import Any, Self

import httpx

from common.models import A2AResult

_JSONRPC = "2.0"
_RPC_PATH = "/"
_CARD_PATH = "/.well-known/agent-card.json"


class A2AError(RuntimeError):
    """A JSON-RPC error returned by the agent (the `error` member was set)."""

    def __init__(self, code: Any, message: str, data: Any = None) -> None:
        super().__init__(f"A2A error {code}: {message}")
        self.code, self.data = code, data


def _text_parts(parts: list[dict] | None) -> list[str]:
    """Pull the text out of an A2A parts array (proto v0.3 JSON: {"kind":"text","text":...})."""
    return [t for p in parts or [] if isinstance(p, dict) and isinstance(t := p.get("text"), str) and t]


def extract_text(result: dict[str, Any]) -> str:
    """Collect every text part from a message- or task-shaped JSON-RPC result, in order."""
    if not isinstance(result, dict):
        return str(result)
    chunks = _text_parts(result.get("parts"))
    chunks += _text_parts((result.get("status") or {}).get("message", {}).get("parts"))
    chunks += [t for art in result.get("artifacts") or [] for t in _text_parts(art.get("parts"))]
    if not chunks:
        chunks = [t for h in result.get("history") or [] if h.get("role") == "agent"
                  for t in _text_parts(h.get("parts"))]
    seen: set[str] = set()
    return "\n".join(c for c in chunks if not (c in seen or seen.add(c)))


class A2ABridgeClient:
    """Minimal A2A client: `message/send` + agent-card fetch, with optional bearer auth."""

    def __init__(
        self, base_url: str = "http://localhost:8080/", token: str | None = None,
        *, timeout: float | None = None,
        transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None,
    ) -> None:
        timeout = timeout if timeout is not None else float(os.environ.get("A2A_CLIENT_TIMEOUT", "600"))
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.base_url = base_url
        self._http = httpx.AsyncClient(base_url=base_url, headers=headers, timeout=timeout, transport=transport)

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
        self, text: str, *, context_id: str | None = None,
        task_id: str | None = None, message_id: str | None = None,
    ) -> A2AResult:
        """Send one text message; return the normalized reply."""
        message: dict[str, Any] = {
            "messageId": message_id or uuid.uuid4().hex,
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
            **({"contextId": context_id} if context_id else {}),
            **({"taskId": task_id} if task_id else {}),
        }
        payload = {"jsonrpc": _JSONRPC, "id": 1, "method": "message/send", "params": {"message": message}}
        r = await self._http.post(_RPC_PATH, json=payload)
        r.raise_for_status()
        body = r.json()
        if body.get("error"):
            err = body["error"]
            raise A2AError(err.get("code"), err.get("message", ""), err.get("data"))
        result = body.get("result") or {}
        status = result.get("status") or {}
        return A2AResult(
            text=extract_text(result), context_id=result.get("contextId"),
            task_id=result.get("taskId") or result.get("id"), state=status.get("state"),
            kind=result.get("kind"), raw=result,
        )
