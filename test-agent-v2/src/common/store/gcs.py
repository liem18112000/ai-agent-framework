"""GcsObjectStore — the Google Cloud Storage adapter for the ObjectStore port.

`google.cloud.storage` (and `google.api_core`) are imported lazily, inside the factory and the write
path, so importing the port/package never requires the GCS client library.
"""

from __future__ import annotations

import os

from common.store.object_store import Blob, CASConflict


class _GcsBlob:
    """Wraps a real `google.cloud.storage.Blob`, translating PreconditionFailed → CASConflict."""

    def __init__(self, blob) -> None:
        self._blob = blob

    @property
    def generation(self) -> int:
        return self._blob.generation

    def download_as_text(self) -> str:
        return self._blob.download_as_text()

    def upload_from_string(self, data, content_type=None, if_generation_match=None) -> None:
        from google.api_core.exceptions import PreconditionFailed

        try:
            self._blob.upload_from_string(
                data, content_type=content_type, if_generation_match=if_generation_match)
        except PreconditionFailed as exc:
            raise CASConflict(str(exc)) from exc


class GcsObjectStore:
    """An `ObjectStore` backed by a `google.cloud.storage.Bucket`."""

    def __init__(self, bucket) -> None:
        self._bucket = bucket

    @classmethod
    def from_env(cls) -> GcsObjectStore:
        """Build from env: GCS_BUCKET (+ optional GCP_PROJECT/VERTEX_PROJECT), as build_bank did."""
        from google.cloud import storage

        project = os.environ.get("GCP_PROJECT") or os.environ.get("VERTEX_PROJECT")
        return cls(storage.Client(project=project).bucket(os.environ["GCS_BUCKET"]))

    def blob(self, path: str) -> Blob:
        return _GcsBlob(self._bucket.blob(path))

    def get_blob(self, path: str) -> Blob | None:
        blob = self._bucket.get_blob(path)
        return _GcsBlob(blob) if blob is not None else None
