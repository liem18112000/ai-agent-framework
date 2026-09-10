"""Ports-and-adapters ObjectStore — a swappable blob store (GCS · local FS · in-memory)."""

from common.store.factory import build_object_store
from common.store.gcs import GcsObjectStore
from common.store.local import LocalObjectStore
from common.store.memory import InMemoryObjectStore
from common.store.object_store import Blob, CASConflict, ObjectStore

__all__ = [
    "Blob",
    "CASConflict",
    "GcsObjectStore",
    "InMemoryObjectStore",
    "LocalObjectStore",
    "ObjectStore",
    "build_object_store",
]
