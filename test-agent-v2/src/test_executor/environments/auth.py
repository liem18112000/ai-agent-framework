"""Per-environment authentication — the prepare phase before a run (slice B; the ledger's `creds_ref`).

`authenticate(cfg, base_url)` runs once per run and returns an `AuthContext` the engines apply:
  - none         — no auth (default)
  - bearer       — `Authorization: Bearer <token>`; token read from a NAMED env var (secret-injected)
  - bearer_fetch — POST a token endpoint on the SAME host, extract a JSON field → bearer (the dynamic
                   luz-get-token flow: a live token per run)
  - login        — a browser login plan (path + fill username/password + submit) BrowserEngine runs first

Secrets come from named env vars (Secret-Manager-injected at deploy), NEVER inline in EXEC_ENVIRONMENTS.
Same-host discipline: a bearer_fetch token endpoint must be on the run's base_url host (reuses the
engines' egress allow-list), so credentials are never POSTed off-site.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from common.monitoring import get_logger

log = get_logger("exec.auth")


@dataclass
class AuthContext:
    """Resolved credentials for a run. `headers` is merged into ApiEngine requests; `login` is a browser
    login plan BrowserEngine runs before the scenario. Empty context = unauthenticated (the default)."""

    headers: dict[str, str] = field(default_factory=dict)
    login: dict | None = None


async def authenticate(cfg: dict | None, *, base_url: str) -> AuthContext:
    """Resolve the auth config into an `AuthContext`. Best-effort: any failure logs and returns an empty
    context (the run proceeds unauthenticated → the SUT's own 401s surface as real failures, not a crash)."""
    cfg = cfg or {}
    kind = str(cfg.get("type", "none")).lower()
    try:
        if kind in ("", "none"):
            return AuthContext()
        if kind == "bearer":
            token = os.environ.get(cfg.get("token_env", ""), "")
            if not token:  # a configured-but-empty token is a broken-creds run, not "no auth" — say so loudly
                log.warning("bearer token env %r resolved EMPTY — run proceeds UNAUTHENTICATED",
                            cfg.get("token_env", ""))
            return AuthContext(headers=_bearer(token))
        if kind == "bearer_fetch":
            return AuthContext(headers=_bearer(await _fetch_token(cfg, base_url=base_url)))
        if kind == "login":
            plan = _login_plan(cfg)
            if not (plan["username"] and plan["password"]):
                log.warning("login creds resolved EMPTY (username_env/password_env) — login will fail")
            return AuthContext(login=plan)
        log.warning("unknown auth type %r — proceeding unauthenticated", kind)
    except Exception as exc:  # noqa: BLE001 — auth failure must not crash the run; the SUT's 401s will show
        log.warning("authenticate(%s) failed: %s — proceeding unauthenticated", kind, type(exc).__name__)
    return AuthContext()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def _login_plan(cfg: dict) -> dict:
    """A browser login plan from config + secret-env-var creds (BrowserEngine fills + submits it)."""
    return {"path": cfg.get("login_path", "/login"),
            "username": os.environ.get(cfg.get("username_env", ""), ""),
            "password": os.environ.get(cfg.get("password_env", ""), ""),
            "user_selector": cfg.get("user_selector", ""),
            "pass_selector": cfg.get("pass_selector", ""),
            "submit_selector": cfg.get("submit_selector", "")}


async def _fetch_token(cfg: dict, *, base_url: str) -> str:
    """POST a token endpoint (same host as base_url) and extract a JSON field → a bearer token. The
    luz-get-token dynamic flow. `token_url` may be a path (joined to base_url) or an absolute same-host
    URL; `token_field` names the JSON field (default 'access_token'); an optional JSON body from a
    named env var. Empty string on any failure (→ unauthenticated)."""
    import httpx

    from test_executor.runners import _same_site
    ref = str(cfg.get("token_url", "")).strip()
    if not ref:
        return ""
    url = str(httpx.URL(base_url).join(ref))
    if not _same_site(url, base_url):     # never POST credentials off the run's own host
        log.warning("token_url %r is off-site for base_url — refusing to fetch a token", ref)
        return ""
    json_body = None
    if cfg.get("body_env"):
        import contextlib
        import json
        with contextlib.suppress(ValueError):
            json_body = json.loads(os.environ.get(cfg["body_env"], "") or "null")
    # Some token endpoints are themselves protected (the Luz security service wants HTTP Basic before it
    # will mint a bearer). `basic_env` names the env var holding the credential — a SECRET, so it is an
    # env-var ref like every other, never inline in EXEC_ENVIRONMENTS. Accepts either already-base64
    # ("dXNlcjpwYXNz") or plain "user:pass", which is encoded here.
    headers = {}
    if cfg.get("basic_env"):
        import base64
        import binascii
        import contextlib
        cred = os.environ.get(cfg["basic_env"], "").strip()
        if cred:
            if ":" in cred:                       # plain user:pass → encode
                cred = base64.b64encode(cred.encode()).decode()
            else:                                 # assume pre-encoded; validate so a typo fails loudly
                with contextlib.suppress(binascii.Error, ValueError):
                    base64.b64decode(cred, validate=True)
            headers["Authorization"] = f"Basic {cred}"
        else:
            log.warning("basic_env %r resolved EMPTY — the token fetch will likely 401", cfg["basic_env"])
    method = str(cfg.get("token_method", "POST")).upper()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.request(method, url, json=json_body, headers=headers or None)
    resp.raise_for_status()
    data = resp.json()
    field_name = cfg.get("token_field", "access_token")
    token = data.get(field_name) if isinstance(data, dict) else None
    if not token:
        log.warning("token response had no %r field", field_name)
        return ""
    return str(token)
