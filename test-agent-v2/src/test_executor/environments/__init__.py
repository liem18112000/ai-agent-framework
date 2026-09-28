"""Target environments + per-environment credentials for the executor (the multi-env model, §4).

`config` parses `EXEC_ENVIRONMENTS` / resolves a named target's `{base_url, auth}`; `auth` turns that
env's auth config into an `AuthContext` (bearer / bearer_fetch / login) from secret *references*, never
the secret value. Naming an environment picks its URL AND its credentials together — hence one package.
"""

from __future__ import annotations

from test_executor.environments.auth import AuthContext, authenticate
from test_executor.environments.config import load_environments, resolve_env

__all__ = ["AuthContext", "authenticate", "load_environments", "resolve_env"]
