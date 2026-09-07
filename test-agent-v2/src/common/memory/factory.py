"""`build_bank()` — the GCS markdown memory bank, in a framework-neutral module.

Lifted out of the a2a-coupled `common/executor.py` (mapping row 5b) so nothing framework-specific
sits between an ADK agent/tool and its bank. `common/executor.py` re-exports this for the legacy
a2a shells during the transition.
"""

from __future__ import annotations

import os


def build_bank():
    """The GCS memory bank from env (GCS_BUCKET, optional GCP_PROJECT/VERTEX_PROJECT)."""
    from google.cloud import storage

    from common.memory import MemoryBank
    from common.memory.pg.project import index_on_write

    client = storage.Client(project=os.environ.get("GCP_PROJECT") or os.environ.get("VERTEX_PROJECT"))
    # on_write enqueues an index-projection job; index_on_write is a no-op under MEMORY_BACKEND=gcs,
    # so this is safe to wire unconditionally and a runtime backend flip needs no bank rebuild.
    return MemoryBank(client.bucket(os.environ["GCS_BUCKET"]), on_write=index_on_write)
