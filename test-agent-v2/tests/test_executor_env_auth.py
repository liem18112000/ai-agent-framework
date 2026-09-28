"""Test Executor slice B — named environments + per-env auth (offline)."""

from __future__ import annotations

import httpx

from test_executor import runners
from test_executor.environments import AuthContext, authenticate, resolve_env
from test_executor.runners import ApiEngine, BrowserEngine, run_suite
from test_executor.store import InMemoryExecStore

_ENVS = ('{"dev":{"base_url":"https://dev.svc","auth":{"type":"bearer","token_env":"DEV_TOKEN"}},'
         '"stg":{"base_url":"https://stg.svc"}}')


# --- environments -------------------------------------------------------------------------------
def test_resolve_env_by_name(monkeypatch):
    monkeypatch.setenv("EXEC_ENVIRONMENTS", _ENVS)
    assert resolve_env("dev")["base_url"] == "https://dev.svc"
    assert "auth" not in resolve_env("stg")   # an env may omit auth entirely
    assert resolve_env("nope") == {}          # unconfigured → {}


def test_resolve_env_bad_json(monkeypatch):
    monkeypatch.setenv("EXEC_ENVIRONMENTS", "{not json")
    assert resolve_env("dev") == {}           # invalid JSON → {} (logged, never crashes)


# --- auth ---------------------------------------------------------------------------------------
async def test_authenticate_none():
    ctx = await authenticate({}, base_url="http://svc")
    assert ctx.headers == {} and ctx.login is None


async def test_authenticate_bearer_from_env(monkeypatch):
    monkeypatch.setenv("DEV_TOKEN", "s3cr3t")
    ctx = await authenticate({"type": "bearer", "token_env": "DEV_TOKEN"}, base_url="http://svc")
    assert ctx.headers == {"Authorization": "Bearer s3cr3t"}


async def test_authenticate_login_plan(monkeypatch):
    monkeypatch.setenv("KUSER", "alice")
    monkeypatch.setenv("KPASS", "pw")
    ctx = await authenticate({"type": "login", "login_path": "/login", "username_env": "KUSER",
                              "password_env": "KPASS", "user_selector": "#u", "pass_selector": "#p",
                              "submit_selector": "#go"}, base_url="http://svc")
    assert ctx.login["username"] == "alice" and ctx.login["user_selector"] == "#u"


async def test_fetch_token_offsite_refused():
    # a token_url on a foreign host must be refused (no creds POSTed off-site) → empty token → no header
    ctx = await authenticate({"type": "bearer_fetch", "token_url": "https://evil.example/token"},
                             base_url="https://dev.svc")
    assert ctx.headers == {}


# --- engines apply auth -------------------------------------------------------------------------
async def test_api_engine_sends_bearer(monkeypatch):
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={})
    monkeypatch.setattr(runners, "_transport", httpx.MockTransport(handler))
    await ApiEngine().run({"request": {"path": "/x", "expect_status": 200}}, base_url="https://dev.svc",
                          auth=AuthContext(headers={"Authorization": "Bearer T"}))
    assert seen["auth"] == "Bearer T"


async def test_browser_engine_logs_in_first(monkeypatch):
    from tests.test_executor_runners import _FakeDriver
    driver = _FakeDriver(body="dashboard")
    monkeypatch.setattr(runners, "_browser_driver", driver)
    auth = AuthContext(login={"path": "/login", "username": "alice", "password": "pw",
                              "user_selector": "#u", "pass_selector": "#p", "submit_selector": "#go"})
    await BrowserEngine().run({"methodology": "ui", "browser": {"url_path": "/home"}},
                              base_url="https://dev.svc", auth=auth)
    # login ran before the scenario: fills + submit recorded, and the login page was visited first
    assert ("fill", "#u", "alice") in driver.actions and ("click", "#go", "") in driver.actions
    assert driver.actions[0] == ("goto", "https://dev.svc/login")


# --- run_suite resolves base_url by env name ----------------------------------------------------
async def test_run_suite_resolves_env_base_url(monkeypatch):
    monkeypatch.setenv("EXEC_RUNNER", "auto")
    monkeypatch.setenv("EXEC_ENVIRONMENTS", _ENVS)
    monkeypatch.setenv("DEV_TOKEN", "tok")
    seen = {}
    monkeypatch.setattr(runners, "_transport",
                        httpx.MockTransport(lambda r: seen.update(url=str(r.url), auth=r.headers.get("authorization"))
                                            or httpx.Response(200, json={})))
    store = InMemoryExecStore()
    # NL api scenario → LLM route needs a provider; give it a bound request so ApiEngine runs directly
    scs = [{"title": "s", "methodology": "api", "request": {"path": "/ping", "expect_status": 200}}]
    await run_suite(store, "CTX", "dev", scenarios=scs)     # no base_url arg → resolved from env "dev"
    assert seen["url"] == "https://dev.svc/ping"            # base_url came from EXEC_ENVIRONMENTS[dev]
    assert seen["auth"] == "Bearer tok"                    # and the env's bearer auth was applied
    envs = await store.list_environments("CTX")
    assert envs[0]["base_url"] == "https://dev.svc" and envs[0]["creds_ref"] == "bearer"


async def test_bearer_fetch_sends_basic_auth_from_env(monkeypatch):
    """A protected token endpoint (the Luz security service wants HTTP Basic before minting a bearer):
    `basic_env` names the env var holding the credential — never inline in EXEC_ENVIRONMENTS."""
    import httpx

    from test_executor.environments.auth import authenticate
    seen = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen["auth"] = r.headers.get("authorization", "")
        return httpx.Response(200, json={"token": "T-123"})

    real = httpx.AsyncClient   # capture BEFORE patching, else the factory recurses into itself
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler)))
    monkeypatch.setenv("LUZ_BASIC", "user:pass")     # plain → base64-encoded by the helper
    ctx = await authenticate({"type": "bearer_fetch", "token_url": "/tok", "token_field": "token",
                              "basic_env": "LUZ_BASIC"}, base_url="https://svc")
    assert seen["auth"] == "Basic dXNlcjpwYXNz"      # b64("user:pass")
    assert ctx.headers.get("Authorization") == "Bearer T-123"


async def test_bearer_fetch_passes_preencoded_basic(monkeypatch):
    import httpx

    from test_executor.environments.auth import authenticate
    seen = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen["auth"] = r.headers.get("authorization", "")
        return httpx.Response(200, json={"token": "T"})

    real = httpx.AsyncClient   # capture BEFORE patching, else the factory recurses into itself
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler)))
    monkeypatch.setenv("LUZ_BASIC", "dXNlcjpwYXNz")  # already base64 → passed through unchanged
    await authenticate({"type": "bearer_fetch", "token_url": "/tok", "token_field": "token",
                        "basic_env": "LUZ_BASIC"}, base_url="https://svc")
    assert seen["auth"] == "Basic dXNlcjpwYXNz"
