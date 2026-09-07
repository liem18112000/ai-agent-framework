#!/usr/bin/env python
"""CLI: (re)derive the pgvector recall tier from the GCS record. See common.memory.pg.backfill.

    uv run python tools/backfill_memory.py
"""

from __future__ import annotations

import asyncio

from common.memory.pg.backfill import run

if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
