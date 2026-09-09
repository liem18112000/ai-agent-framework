"""`build_bank()` — the GCS markdown memory bank, in a framework-neutral module."""

from __future__ import annotations

import os


def build_bank():
    """The GCS memory bank from env (GCS_BUCKET, optional GCP_PROJECT/VERTEX_PROJECT)."""
    from google.cloud import storage

    from common.memory import MemoryBank
    from common.memory.pg.project import index_on_write

    return MemoryBank(storage.Client(project=os.environ.get("GCP_PROJECT") or os.environ.get("VERTEX_PROJECT")).bucket(os.environ["GCS_BUCKET"]), on_write=index_on_write)
