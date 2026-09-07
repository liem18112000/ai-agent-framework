"""Bridge data contracts — the normalized A2A reply the A2A->MCP client returns.

Pure data holder: `A2AResult` collapses the agent's two response shapes (a plain Message
or a multi-turn Task) into one small record the bridge and MCP layer read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class A2AResult:
    """One normalized reply, whether the agent returned a Message or a Task."""

    text: str                    # every text part, joined with newlines
    context_id: str | None       # A2A conversation id — reuse to continue a session
    task_id: str | None          # A2A task id — reuse to answer a paused (input-required) task
    state: str | None            # task state ("input-required" / "completed" / ...); None for a message
    kind: str | None             # "message" | "task"
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_complete(self) -> bool:
        """A plain message reply, or a task that reached a terminal 'completed' state."""
        return self.state in (None, "completed")
