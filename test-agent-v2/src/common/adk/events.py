"""Tiny shared helpers for custom BaseAgents — read the turn's user text, emit a text Event."""

from __future__ import annotations

from google.adk.events import Event, EventActions
from google.genai import types


def incoming_text(ctx) -> str:
    """The latest user-role text part in the session (the current turn's input)."""
    for ev in reversed(getattr(ctx.session, "events", []) or []):
        c = getattr(ev, "content", None)
        if c and getattr(c, "role", None) == "user" and (c.parts or []):
            for p in c.parts:
                if getattr(p, "text", None):
                    return p.text
    return ""


def text_event(author: str, text: str, *, state_delta: dict | None = None) -> Event:
    """A model-authored text Event, optionally carrying a session state_delta (the checkpoint)."""
    kwargs = {"author": author, "content": types.Content(role="model", parts=[types.Part(text=text)])}
    if state_delta:  # Event.actions must be an EventActions, never None — omit it otherwise
        kwargs["actions"] = EventActions(state_delta=state_delta)
    return Event(**kwargs)
