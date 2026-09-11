"""`cloud_providers()` — the configured CloudProvider adapters, selected by env (KGA_CLOUD_PROVIDERS).

Registering a new cloud is one line in `_REGISTRY` (e.g. `"azure": AzureCloudProvider`) — no neutral
code changes. Adapters are cheap to construct (SDK clients are built lazily on first reach)."""

from __future__ import annotations

import os

from common.cloud.gcp import GcpCloudProvider
from common.cloud.provider import CloudProvider

# A new provider adapter registers HERE (single extension point): _REGISTRY["aws"] = AwsCloudProvider
_REGISTRY: dict[str, type] = {
    "gcp": GcpCloudProvider,
}


def cloud_providers() -> dict[str, CloudProvider]:
    """The configured adapters keyed by name — `KGA_CLOUD_PROVIDERS` (comma-separated, default 'gcp').
    Unknown names are skipped with a note, never an error."""
    names = os.environ.get("KGA_CLOUD_PROVIDERS", "gcp").split(",")
    return {n: _REGISTRY[n]() for name in names if (n := name.strip()) in _REGISTRY}
