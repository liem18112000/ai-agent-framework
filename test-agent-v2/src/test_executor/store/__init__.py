"""The per-environment run ledger (Design ref: RESEARCH-test-executor-agent.md §4).

Postgres on the SHARED Cloud SQL engine (`sql.ExecStore`), with an in-memory fallback offline
(`memory.InMemoryExecStore`), selected by `factory.build_store`. Split into: `ids` (id/JSON helpers),
`sql` (the Postgres ledger + schema), `memory` (the offline ledger), `factory` (the memoized selector).
"""

from __future__ import annotations

from test_executor.store.factory import build_store
from test_executor.store.ids import _j, _now, env_id, new_id
from test_executor.store.memory import InMemoryExecStore
from test_executor.store.sql import ExecStore

__all__ = ["ExecStore", "InMemoryExecStore", "_j", "_now", "build_store", "env_id", "new_id"]
