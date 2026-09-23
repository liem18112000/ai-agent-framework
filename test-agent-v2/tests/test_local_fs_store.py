"""LocalFsObjectStore — CAS/generation + iter/delete round-trip (the shared-FS local-run store)."""

from __future__ import annotations

import pytest

from common.store import CASConflict
from common.store.local import LocalFsObjectStore


def test_write_read_generation_and_cas(tmp_path):
    s = LocalFsObjectStore(tmp_path)
    assert s.get_blob("a/b.md") is None

    b = s.blob("a/b.md")
    b.upload_from_string("v1")  # first write: gen 0 -> 1
    got = s.get_blob("a/b.md")
    assert got is not None and got.download_as_text() == "v1" and got.generation == 1

    got.upload_from_string("v2", if_generation_match=1)  # CAS success (match current gen)
    assert s.get_blob("a/b.md").generation == 2
    with pytest.raises(CASConflict):  # stale CAS raises
        s.blob("a/b.md").upload_from_string("v3", if_generation_match=1)
    assert s.get_blob("a/b.md").download_as_text() == "v2"  # unchanged after conflict


def test_iter_excludes_meta_and_delete(tmp_path):
    s = LocalFsObjectStore(tmp_path)
    s.blob("p/x").upload_from_string("1")
    s.blob("p/y").upload_from_string("2")
    s.blob("q/z").upload_from_string("3")
    names = sorted(b.name for b in s.iter_blobs("p/"))
    assert names == ["p/x", "p/y"]  # prefix filter + no .meta sidecars leak
    assert s.delete("p/x") is True and s.delete("p/x") is False
    assert s.get_blob("p/x") is None
