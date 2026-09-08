"""Tiny shared helpers for custom BaseAgents/plugins — the turn's user text, a UTC stamp, a text Event."""

from __future__ import annotations

import datetime

from google.adk.events import Event, EventActions
from google.genai import types


def incoming_text(ctx) -> str:
    """The current turn's user text. ADK hands it to us directly as the InvocationContext's
    `user_content` — no need to walk `session.events` ourselves."""
    for part in getattr(getattr(ctx, "user_content", None), "parts", None) or []:
        if getattr(part, "text", None):
            return part.text
    return ""


def now() -> str:
    """UTC stamp in the engine's filename-safe format. Mirrors `common.executor.now`, re-derived here
    because that module pulls in the a2a-sdk shell this ADK layer replaced."""
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H-%M-%SZ")


def text_event(author: str, text: str, *, state_delta: dict | None = None) -> Event:
    """A model-authored text Event, optionally carrying a session state_delta (the checkpoint)."""
    kwargs = {"author": author, "content": types.Content(role="model", parts=[types.Part(text=text)])}
    if state_delta:  # Event.actions must be an EventActions, never None — omit it otherwise
        kwargs["actions"] = EventActions(state_delta=state_delta)
    return Event(**kwargs)
