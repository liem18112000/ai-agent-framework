"""LocalFsObjectStore — a shared-filesystem ObjectStore for local / docker-compose runs (no GCP).

Same tiny Blob/CAS contract as GcsObjectStore + InMemoryObjectStore, but persisted under one directory
(a docker-compose shared volume, or a host dir) so the four agent containers see ONE memory bank —
the cross-service state the pipeline passes between KGA -> TPD -> TEV. Content files hold the object
bytes verbatim (so `iter_blobs`/`download_as_text` are natural); generation + a write lock live in a
sibling `.meta/` tree, kept out of `iter_blobs`. The lock (O_EXCL spin, portable Win+Linux) makes the
index RMW/CAS race-safe across processes — the one corner that would otherwise lose writes.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from common.store.object_store import Blob, CASConflict

_META = ".meta"  # generation + lock sidecar tree; excluded from iter_blobs


class _LocalBlob:
    def __init__(self, store: LocalFsObjectStore, name: str) -> None:
        self._store, self.name = store, name

    @property
    def generation(self) -> int:
        return self._store._gen(self.name)

    def download_as_text(self) -> str:
        return self._store._path(self.name).read_text(encoding="utf-8")

    def upload_from_string(self, data, content_type=None, if_generation_match=None) -> None:
        self._store._write(self.name, data, if_generation_match)


class LocalFsObjectStore:
    """An `ObjectStore` rooted at a directory. Blob paths map to files under it (`/` = subdirs)."""

    def __init__(self, root: str | os.PathLike) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> LocalFsObjectStore:
        return cls(os.environ.get("STORE_LOCAL_DIR", "/data/memory"))

    # --- path mapping (guard against escaping the root via a crafted key) ---
    def _path(self, name: str) -> Path:
        p = (self.root / name).resolve()
        if self.root not in p.parents and p != self.root:
            raise ValueError(f"path escapes store root: {name!r}")
        return p

    def _meta(self, name: str, suffix: str) -> Path:
        return self._path(f"{_META}/{name}{suffix}")

    def _gen(self, name: str) -> int:
        g = self._meta(name, ".gen")
        try:
            return int(g.read_text())
        except (FileNotFoundError, ValueError):
            return 0

    def _write(self, name: str, data, if_generation_match) -> None:
        lock = self._meta(name, ".lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        fd = self._acquire(lock)
        try:
            cur = self._gen(name)
            if if_generation_match is not None and if_generation_match != cur:
                raise CASConflict(f"generation mismatch: have {cur}, expected {if_generation_match}")
            path = self._path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(data if isinstance(data, str) else data.decode("utf-8"), encoding="utf-8")
            os.replace(tmp, path)  # atomic swap
            self._meta(name, ".gen").write_text(str(cur + 1))
        finally:
            os.close(fd)
            lock.unlink(missing_ok=True)

    @staticmethod
    def _acquire(lock: Path, *, timeout: float = 5.0) -> int:
        """Portable cross-process mutex: create the lockfile O_EXCL, spinning until it's free."""
        deadline = time.monotonic() + timeout
        while True:
            try:
                return os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if time.monotonic() > deadline:
                    lock.unlink(missing_ok=True)  # stale lock from a crashed writer — reclaim
                    continue
                time.sleep(0.02)

    # --- ObjectStore protocol ---
    def blob(self, path: str) -> Blob:
        return _LocalBlob(self, path)

    def get_blob(self, path: str) -> Blob | None:
        return _LocalBlob(self, path) if self._path(path).is_file() else None

    def iter_blobs(self, prefix: str) -> list[Blob]:
        if not self.root.exists():
            return []
        out = []
        for p in self.root.rglob("*"):
            if not p.is_file():
                continue
            name = p.relative_to(self.root).as_posix()
            if name.startswith(_META + "/") or not name.startswith(prefix):
                continue
            out.append(_LocalBlob(self, name))
        return out

    def delete(self, path: str) -> bool:
        p = self._path(path)
        existed = p.is_file()
        p.unlink(missing_ok=True)
        self._meta(path, ".gen").unlink(missing_ok=True)
        return existed
