"""Id + JSON helpers shared by the run-ledger backends."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def env_id(context_id: str, name: str) -> str:
    return f"{context_id}:{name}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _j(v):
    """asyncpg hands back jsonb as a str for raw text() queries — decode it; pass through dict/list/None."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v
