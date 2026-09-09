"""Tiny shared helpers for custom BaseAgents/plugins — the turn's user text, a UTC stamp, a text Event."""

from __future__ import annotations

import datetime

from google.adk.events import Event, EventActions
from google.genai import types


def incoming_text(ctx) -> str:
    """The current turn's user text. ADK hands it to us directly as the InvocationContext's"""
    parts = getattr(getattr(ctx, "user_content", None), "parts", None) or []
    return next((p.text for p in parts if getattr(p, "text", None)), "")


def now() -> str:
    """UTC stamp in the engine's filename-safe format. Mirrors `common.executor.now`, re-derived here"""
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")


def text_event(author: str, text: str, *, state_delta: dict | None = None) -> Event:
    """A model-authored text Event, optionally carrying a session state_delta (the checkpoint)."""
    kwargs = {"author": author, "content": types.Content(role="model", parts=[types.Part(text=text)])}
    return Event(**kwargs, actions=EventActions(state_delta=state_delta)) if state_delta else Event(**kwargs)
