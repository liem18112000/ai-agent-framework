"""`cloud_providers()` — the configured CloudProvider adapters, selected by env (KGA_CLOUD_PROVIDERS).

One adapter today (GCP); when a second (Azure/AWS) lands, add a branch in `cloud_providers`. Adapters
are cheap to construct (SDK clients are built lazily on first reach)."""

from __future__ import annotations

import os

from common.cloud.gcp import GcpCloudProvider
from common.cloud.provider import CloudProvider


def cloud_providers() -> dict[str, CloudProvider]:
    """The configured adapters keyed by name — `KGA_CLOUD_PROVIDERS` (comma-separated, default 'gcp').
    Only 'gcp' is registered today; an unknown name is skipped, never an error."""
    names = {n for name in os.environ.get("KGA_CLOUD_PROVIDERS", "gcp").split(",") if (n := name.strip())}
    return {"gcp": GcpCloudProvider()} if "gcp" in names else {}
