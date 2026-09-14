"""ObjectStore port — the blob-store contract MemoryBank duck-types (GCS today, swappable).

Importing this module pulls in nothing but stdlib, so the port is safe to reference from anywhere
(offline/test runs never touch the GCS client library — that lives behind the `gcs` adapter).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable


class CASConflict(Exception):
    """Optimistic-concurrency (compare-and-set) conflict on a write.

    The domain replacement for the leaked `google.api_core.exceptions.PreconditionFailed`: raised
    when `upload_from_string(..., if_generation_match=g)` and `g` != the stored generation.
    """


@runtime_checkable
class Blob(Protocol):
    """A single stored object. `generation` is a token that bumps on every successful write."""

    generation: int
    name: str

    def download_as_text(self) -> str: ...

    def upload_from_string(self, data, content_type=None, if_generation_match=None) -> None:
        """Write `data`. If `if_generation_match` is set and != `generation`, raise `CASConflict`."""
        ...


@runtime_checkable
class ObjectStore(Protocol):
    """A bucket of blobs keyed by path."""

    def blob(self, path: str) -> Blob:
        """A blob handle for writing at `path` (the object need not exist yet)."""
        ...

    def get_blob(self, path: str) -> Blob | None:
        """The blob at `path`, or None if it does not exist."""
        ...

    def iter_blobs(self, prefix: str) -> Iterable[Blob]:
        """Yield every blob whose path starts with `prefix` (empty prefix = all). Each has `.name`."""
        ...

    def delete(self, path: str) -> bool:
        """Delete the blob at `path`. Return True if it existed. Idempotent (missing → False)."""
        ...
