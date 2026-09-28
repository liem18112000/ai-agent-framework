"""Cloud-neutral knobs for the KGA tiers 5/6/7. There is NO separate on/off flag: the tier is enabled
exactly when a provider's env map is configured (KGA_GCP_ENV_MATRIX / _FILE, per adapter). Per-provider
config (env matrix, the `gcp` extra) stays inside each adapter — these are the neutral knobs."""

from __future__ import annotations

import os

from common.env import env_int

_DEFAULT_WINDOWS = (7, 14, 21, 28)


def cloud_configured() -> bool:
    """The tier's SOLE enablement signal: at least one configured provider has a NON-EMPTY env map.
    `KGA_CLOUD_PROVIDERS` always yields ≥1 registered provider, so the real signal is a non-empty env
    map (from KGA_GCP_ENV_MATRIX / _FILE). No env entries → False → tiers 5/6/7 no-op."""
    from common.cloud.factory import cloud_providers

    return any(p.env_keys() for p in cloud_providers().values())


def cloud_max_services(default: int = 8) -> int:
    """Cap on promoted `cloudsvc:` seeds (`KGA_CLOUD_MAX_SERVICES`); non-int falls back to `default`."""
    return env_int("KGA_CLOUD_MAX_SERVICES", default)


def cloud_windows() -> tuple[int, ...]:
    """The expanding log-window days (`KGA_CLOUD_WINDOWS`, comma-separated) or (7,14,21,28)."""
    raw = os.environ.get("KGA_CLOUD_WINDOWS", "").strip()
    if not raw:
        return _DEFAULT_WINDOWS
    try:
        days = tuple(int(x) for x in raw.split(",") if x.strip())
        return days or _DEFAULT_WINDOWS
    except ValueError:
        return _DEFAULT_WINDOWS
