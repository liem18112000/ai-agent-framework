"""Bridge data contracts — the normalized A2A reply the A2A->MCP client returns."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class A2AResult:
    """One normalized reply, whether the agent returned a Message or a Task."""

    text: str
    context_id: str | None
    task_id: str | None
    state: str | None
    kind: str | None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_complete(self) -> bool:
        """A plain message reply, or a task that reached a terminal 'completed' state."""
        return self.state in (None, "completed")
