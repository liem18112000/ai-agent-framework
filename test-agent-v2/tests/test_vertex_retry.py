"""ADK-02 — bounded retry/backoff on transient Vertex/Anthropic errors."""

from __future__ import annotations

import types

import httpx
from anthropic import APIStatusError, AuthenticationError

from common.llm import vertex


def _status_error(status: int) -> APIStatusError:
    resp = httpx.Response(status, request=httpx.Request("POST", "https://vertex.example/v1"))
    return APIStatusError("boom", response=resp, body=None)


def _msg():
    return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="ok")])


class _FakeStream:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return _msg()


def _install(monkeypatch, stream_impl):
    """Wire a fake AnthropicVertex whose messages.stream runs `stream_impl` and skip real sleeps."""
    fake = types.SimpleNamespace(messages=types.SimpleNamespace(stream=stream_impl))
    monkeypatch.setattr(vertex, "_client", lambda project, location: fake)
    monkeypatch.setattr(vertex.time, "sleep", lambda *_: None)


def test_transient_503_then_success_returns_completion(monkeypatch):
    calls = {"n": 0}

    def stream(**_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _status_error(503)
        return _FakeStream()

    _install(monkeypatch, stream)
    out = vertex.complete("hi", project="p", location="l", model="m", max_tokens=10)
    assert out == "ok"
    assert calls["n"] == 2  # one failure, one retry that succeeded


def test_auth_error_is_not_retried(monkeypatch):
    calls = {"n": 0}

    def stream(**_kwargs):
        calls["n"] += 1
        resp = httpx.Response(401, request=httpx.Request("POST", "https://vertex.example/v1"))
        raise AuthenticationError("nope", response=resp, body=None)

    _install(monkeypatch, stream)
    try:
        vertex.complete("hi", project="p", location="l", model="m", max_tokens=10)
        raise AssertionError("expected AuthenticationError to propagate")
    except AuthenticationError:
        pass
    assert calls["n"] == 1  # 4xx auth error fails fast, no retry
