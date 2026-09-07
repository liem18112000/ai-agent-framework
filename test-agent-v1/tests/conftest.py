"""Shared test fakes/fixtures — an in-memory GCS bucket (generation + CAS) and a
loader that hydrates one from a saved pack fixture under tests/fixtures/.
"""

from __future__ import annotations

import pathlib

import pytest
from google.api_core.exceptions import PreconditionFailed

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


class FakeBlob:
    def __init__(self, bucket, name):
        self._b, self.name = bucket, name

    @property
    def generation(self):
        return self._b.gens.get(self.name, 0)

    def download_as_text(self):
        return self._b.store[self.name]

    def upload_from_string(self, data, content_type=None, if_generation_match=None):
        cur = self._b.gens.get(self.name, 0)
        if if_generation_match is not None and if_generation_match != cur:
            raise PreconditionFailed("generation mismatch")
        self._b.store[self.name] = data
        self._b.gens[self.name] = cur + 1


class FakeBucket:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.gens: dict[str, int] = {}

    def blob(self, name):
        return FakeBlob(self, name)

    def get_blob(self, name):
        return FakeBlob(self, name) if name in self.store else None


def load_fixture_bucket(pack_name: str) -> FakeBucket:
    """Hydrate a FakeBucket from tests/fixtures/<pack_name>/ (keys = paths under it)."""
    bucket = FakeBucket()
    root = FIXTURES / pack_name
    for path in root.rglob("*.json"):
        key = path.relative_to(root).as_posix()
        bucket.store[key] = path.read_text(encoding="utf-8")
        bucket.gens[key] = 1
    return bucket


@pytest.fixture
def fake_bucket() -> FakeBucket:
    return FakeBucket()


@pytest.fixture
def pack_bucket() -> FakeBucket:
    return load_fixture_bucket("pack_run-6f2a")
