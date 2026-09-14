"""LocalObjectStore — a filesystem ObjectStore adapter (path → file under `root`).

Generations are tracked in a small JSON index sidecar (`.generations.json` at `root`) so the CAS
contract MemoryBank relies on holds across writes (read fresh each op).
"""

from __future__ import annotations

import json
from pathlib import Path

from common.store.object_store import Blob, CASConflict


class _LocalBlob:
    def __init__(self, store: LocalObjectStore, path: str) -> None:
        self._store, self.name = store, path

    @property
    def generation(self) -> int:
        return self._store._gen(self.name)

    def download_as_text(self) -> str:
        return self._store._file(self.name).read_text(encoding="utf-8")

    def upload_from_string(self, data, content_type=None, if_generation_match=None) -> None:
        self._store._write(self.name, data, if_generation_match)


class LocalObjectStore:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._index = self._root / ".generations.json"

    def _file(self, path: str) -> Path:
        return self._root / path

    def _load_gens(self) -> dict[str, int]:
        try:
            return json.loads(self._index.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}

    def _gen(self, path: str) -> int:
        return self._load_gens().get(path, 0)

    def _write(self, path: str, data: str, if_generation_match) -> None:
        gens = self._load_gens()
        cur = gens.get(path, 0)
        if if_generation_match is not None and if_generation_match != cur:
            raise CASConflict(f"generation mismatch for {path}: {if_generation_match} != {cur}")
        f = self._file(path)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(data, encoding="utf-8")
        gens[path] = cur + 1
        self._root.mkdir(parents=True, exist_ok=True)
        self._index.write_text(json.dumps(gens, indent=1), encoding="utf-8")

    def blob(self, path: str) -> Blob:
        return _LocalBlob(self, path)

    def get_blob(self, path: str) -> Blob | None:
        return _LocalBlob(self, path) if self._file(path).exists() else None

    def iter_blobs(self, prefix: str):
        # ponytail: deferred — no caller selects STORE_BACKEND=local today (admin runs on gcs/memory).
        raise NotImplementedError("LocalObjectStore.iter_blobs — no caller yet (admin uses gcs/memory)")

    def delete(self, path: str) -> bool:
        raise NotImplementedError("LocalObjectStore.delete — no caller yet (admin uses gcs/memory)")
