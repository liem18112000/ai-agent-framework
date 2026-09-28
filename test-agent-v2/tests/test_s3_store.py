"""S3ObjectStore CAS/round-trip — INTEGRATION test against a live S3/MinIO (set S3_ENDPOINT_URL+S3_BUCKET).

Skips cleanly offline. Run after `docker compose up` (MinIO) with the .env.compose S3_* exported, or:
  S3_ENDPOINT_URL=http://localhost:9000 S3_BUCKET=testagent-memory \
  S3_ACCESS_KEY=minioadmin S3_SECRET_KEY=minioadmin pytest tests/test_s3_store.py
"""

from __future__ import annotations

import os
import uuid

import pytest

from common.store import CASConflict
from common.store.s3 import S3ObjectStore

pytestmark = pytest.mark.skipif(not os.environ.get("S3_ENDPOINT_URL"),
                                reason="no S3_ENDPOINT_URL (live MinIO/S3 required)")


def test_generation_cas_roundtrip():
    s = S3ObjectStore.from_env()
    key = f"itest/{uuid.uuid4().hex}.md"
    assert s.get_blob(key) is None

    s.blob(key).upload_from_string("v1", if_generation_match=0)   # create-only
    b = s.get_blob(key)
    assert b is not None and b.download_as_text() == "v1" and b.generation == 1

    with pytest.raises(CASConflict):  # re-create must fail
        s.blob(key).upload_from_string("dup", if_generation_match=0)

    s.blob(key).upload_from_string("v2", if_generation_match=1)   # replace-if-unchanged
    assert s.get_blob(key).generation == 2
    with pytest.raises(CASConflict):  # stale generation
        s.blob(key).upload_from_string("v3", if_generation_match=1)

    assert key in {b.name for b in s.iter_blobs("itest/")}
    assert s.delete(key) is True and s.get_blob(key) is None
