"""Named target environments for the executor — the multi-env model (§4).

`EXEC_ENVIRONMENTS` is a JSON map `{name: {base_url, auth}}` (mirrors the repo's `KGA_GCP_ENV_MATRIX`
JSON-config convention). `run_suite(env=name)` resolves the target `base_url` + `auth` config from here,
so NAMING an environment picks its URL + credentials — the multi-env model, instead of one service-wide
`EXEC_BASE_URL`. Falls back to `EXEC_BASE_URL` (the single-target shortcut) when the named env isn't
configured. The ledger records `base_url` + the auth KIND (never the secret; secrets are env-var refs).
"""

from __future__ import annotations

import json
import os

from common.monitoring import get_logger

log = get_logger("exec.environments")


def load_environments() -> dict[str, dict]:
    """Parse `EXEC_ENVIRONMENTS` (JSON `{name: {base_url, auth}}`) → dict, or {} when unset/invalid."""
    raw = os.environ.get("EXEC_ENVIRONMENTS", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError as exc:
        log.warning("EXEC_ENVIRONMENTS is not valid JSON (%s) — ignoring", exc)
        return {}
    return data if isinstance(data, dict) else {}


def resolve_env(name: str) -> dict:
    """The named environment's config (`{base_url, auth}`), or {} when it isn't configured."""
    return load_environments().get(name.strip()) or {}
