"""InMemoryObjectStore — the canonical in-memory ObjectStore (path → text + generation).

The production-grade equivalent of the tests' FakeBucket: identical generation/CAS semantics, but
raising the domain `CASConflict` on an `if_generation_match` mismatch.
"""

from __future__ import annotations

from common.store.object_store import Blob, CASConflict


class _InMemoryBlob:
    def __init__(self, store: InMemoryObjectStore, name: str) -> None:
        self._store, self.name = store, name

    @property
    def generation(self) -> int:
        return self._store.gens.get(self.name, 0)

    def download_as_text(self) -> str:
        return self._store.store[self.name]

    def upload_from_string(self, data, content_type=None, if_generation_match=None) -> None:
        cur = self._store.gens.get(self.name, 0)
        if if_generation_match is not None and if_generation_match != cur:
            raise CASConflict("generation mismatch")
        self._store.store[self.name] = data
        self._store.gens[self.name] = cur + 1


class InMemoryObjectStore:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.gens: dict[str, int] = {}

    def blob(self, path: str) -> Blob:
        return _InMemoryBlob(self, path)

    def get_blob(self, path: str) -> Blob | None:
        return _InMemoryBlob(self, path) if path in self.store else None
