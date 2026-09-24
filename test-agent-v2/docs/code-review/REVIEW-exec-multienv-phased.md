# Code Review — Test-Executor multi-env / credentials / OpenAPI / file-upload

**Date:** 2026-09-24 (round 3) · **Baseline:** green (`716 passed, 15 skipped`) · **Scope:** the surface added since the executor review earlier today — `auth.py` (per-env credentials), `environments.py`/`resolve_env` (`EXEC_ENVIRONMENTS`), `openapi.py` (OpenAPI-grounded execution), ApiEngine **multipart file upload** + `file-data-ref` scenarios.
**Method:** two focused security reviewers, full data-flow traces (config → resolve → engine → store → client), grep-verified.

The prior round's egress allow-list (`_same_site`) and the "secret reference, never value" mandate (design §3.3) are the invariants under test here.

---

## Scorecard

| Lens | Result |
|---|---|
| Correctness / Security | **2 P1 · 5 P2 · 3 P3** |
| Over-engineering | 1 clean deletion (the dead `open(path)` upload sink) |
| Overall | The credential path largely honors the mandate — the bearer token only ever reaches httpx `headers=`, `EXEC_ENVIRONMENTS` carries env-var **names** not secrets, `creds_ref` records only the auth KIND, and egress is pinned per-run. The risk is **(a)** a *false-green* failure mode (broken creds → silent-unauthenticated → 401-as-pass) that invisibly defeats the executor's assurance, and **(b)** three residual egress/leak gaps the hardening elsewhere implies are already closed. |

---

## Phase plan

| Phase | Theme | Findings |
|---|---|---|
| **0** | Assurance & egress | AUTH-01 (P1), SINK-01 (P1), EGRESS-01 (P2), FILE-01/SINK-02 (P2, delete) |
| **1** | Data-safety / robustness | LEAK-01 (P2), LEAK-02 (P2), SINK-03 (P2) |
| **2** | Nits | deps (P3), upload_cases docstring (P3), b64 guard (P3) |

---

## Phase 0 — Assurance & egress

### AUTH-01 · Broken credentials → silent-unauthenticated run where 401/403 counts as PASS (false-green) · **P1** · `auth.py:42-56`, `runners.py:120`
Two compounding causes on the reachable `EXEC_RUNNER=auto` path: (1) `authenticate` with `type=bearer` reads `os.environ.get(cfg["token_env"], "")`; a missing/typo'd `token_env` → `""` → `_bearer("")` returns `{}` **silently** (no warning), so the run proceeds with no `Authorization` header. (2) ApiEngine scores `ok_status = (status == expect) if expect else (status < 500)`, and most scenarios have `expect_status=0`, so a **401/403 is `<500` → PASS**. Net: a fat-fingered `token_env` yields a suite that runs entirely unauthenticated, the SUT 401s every call, and `run_suite` reports `passed=N, failed=0` — a green run that tested nothing, hiding broken credentials. This directly defeats the executor's core assurance. **Fix:** (a) in `authenticate`, when a real auth `type` resolves to empty creds, `log.warning` + record `auth_unresolved` in the run signals; (b) in ApiEngine, an unexpected 401/403 is never conformant: `else (status < 500 and status not in (401, 403))`.

### SINK-01 · OpenAPI `$ref` resolution bypasses the egress allow-list (blind SSRF + file read) · **P1** · `openapi.py:110-116`
`Draft7Validator(schema, resolver=RefResolver.from_schema(spec)).validate(body)` resolves `$ref`s lazily; jsonschema's `RefResolver` fetches absolute `http(s)://` refs and reads `file://` refs directly — **none routed through `_same_site`**. A tampered/attacker-controlled SUT spec with `"$ref": "http://metadata.google.internal/…"` or `"file:///etc/passwd"` triggers that fetch/read from inside the agent during response validation. Blind (result swallowed), so it's an egress-allow-list bypass / SSRF side-effect. **Fix:** disable remote resolution before validating — set `resolver.resolve_remote` to raise; in-document `#/…` refs still work, and the existing broad `except` degrades to "schema check skipped".

### EGRESS-01 · `_same_site` pins host only — same-host different-port/scheme pivot passes · **P2** · `runners.py:42`
The allow-list compares `u.host == base_url.host` but ignores **port and scheme**. On the internal/localhost test envs this executor targets, a scenario `goto`/request to `http://<base-host>:2375/…` (docker API) or another admin port is "same host" and passes — a residual SSRF the guard's own docstring implies it blocks. **Fix:** compare the full origin `(scheme, host, effective-port)` (normalize default ports 80/443).

### FILE-01 / SINK-02 · Ungated `open(up["path"])` arbitrary-file-read upload sink · **P2 (delete)** · `runners.py:339-341`
`_send_kwargs` will `open()` any `request.upload.path` and POST its bytes to the SUT. **Currently unreachable** on the live path (the LLM scenario schema has no `request` field; `upload_cases` only emits inline `content`/`data_ref`), so it's a latent read-any-file-and-exfil primitive kept for a docstring-claimed "offline/CLI use" with no caller. Both reviewers flagged it. **Fix (ponytail):** delete the `path` branch, keep inline `content` only (~−6 LOC); re-add if a real CLI needs it.

---

## Phase 1 — Data-safety / robustness

### LEAK-01 · Full `base_url` (incl. any userinfo) persisted to Postgres + returned to the client · **P2** · `runner.py:179,203`, `store.py:97-115`, `ops.py:41`
ApiEngine deliberately builds a host-free failure string ("keeps any base_url userinfo/creds out of the ledger") — but `run_suite` passes the **raw** `base_url` to `upsert_env`, which writes it verbatim to `exec_environment.base_url`, and `list_environments`→`render_envs` prints `name [https://user:secret@host]` back to the client. The one hardened spot is undercut by the ledger row + the list reply. **Fix:** strip userinfo once at resolution: `base_url = str(httpx.URL(base_url).copy_with(username=None, password=None))`.

### LEAK-02 · BrowserEngine echoes the raw `{exc}` into a persisted + client-facing message · **P2** · `runners.py:255`
`f"browser run failed: {exc}"` lands the full exception in `failures[].message` → Postgres + client reply; ApiEngine deliberately uses `type(exc).__name__` and logs full detail server-side. BrowserEngine runs `_do_login` (fills a password), so worst case an error surfaces internal detail into that sink. **Fix:** mirror ApiEngine — `type(exc).__name__` in the outcome, `log.warning(... exc)` server-side.

### SINK-03 · `fetch_spec` reads the OpenAPI spec fully into RAM, no size cap (+ YAML alias-bomb) · **P2** · `openapi.py:33-40`
`resp.json()` / `yaml.safe_load(resp.text)` with no `content-length`/streaming cap, unlike ApiEngine's `_MAX_RESPONSE_BYTES` guard; the spec body is from the SUT (a giant/alias-expanded spec → OOM on the 2Gi agent; `safe_load` does not stop anchor bombs). **Fix:** stream + cap the spec fetch (reuse `_MAX_RESPONSE_BYTES`), or precheck content-length.

---

## Phase 2 — Nits
- **DEP-01 · P3** `jsonschema` + `pyyaml` are lazy-imported but undeclared in `pyproject.toml`; on a clean image Pillar-3 silently degrades. Add them (or an `exec` extra) if Pillar 3 runs in prod.
- **DOC-01 · P3** `scenarios.py:upload_cases` docstring claims "happy + a non-file negative" but returns `[happy]` only — fix the docstring or add the negative.
- **B64-01 · P3** `runner.py:_resolve_upload_refs` `base64.b64decode(spec["b64"])` is outside the try → a malformed fixture wedges the chunk. Not attacker-reachable; wrap to degrade the one upload.

---

## ✅ Resolution (2026-09-24)

Fixed phase by phase; suite **716 → 721 passed, 15 skipped, 0 failed**, `ruff check src/` clean. Not committed.

| Phase | Findings | Status |
|---|---|---|
| **0 — Assurance/egress** | AUTH-01 (a) `authenticate` warns loudly when a real auth type resolves to empty creds; (b) ApiEngine scores an unexpected 401/403 as a **failure** not a pass · SINK-01 openapi `$ref` remote/`file://` resolution blocked (`resolver.resolve_remote` raises) · EGRESS-01 `_same_site` now pins the full **origin** (scheme+host+port, default-port-normalized) · FILE-01 deleted the `open(up["path"])` upload branch (inline `content` only) · **EXEC-JEV-01** restored `DecisionProvider.choice()` (deleted round-1 as 0-caller; the executor's `_jev_bucket` triage re-added a caller → JEV triage was dead-on-arrival, silently degrading to the heuristic) + regression test | **Done** |
| **1 — Data-safety/robustness** | LEAK-01 userinfo stripped from `base_url` before persist/echo · LEAK-02 BrowserEngine failure message uses `type(exc).__name__` (full detail server-side) · SINK-03 `fetch_spec` streamed + `_MAX_SPEC_BYTES` cap | **Done** |
| **2 — Nits** | DEP-01 `jsonschema`/`pyyaml` declared as a scoped `exec` extra · B64-01 fixture decode guarded (degrades one upload, not the run) | **Done** |

**Not code-changed:** DOC-01 (`upload_cases` "happy + negative" docstring drift) — left as a note; `scenarios.py`/`upload_cases` is under active concurrent rewrite, so the docstring is best fixed by the author landing that feature. The YAML alias-bomb residual on `fetch_spec` is bounded by the byte cap (noted with a `ponytail:` comment; a custom loader isn't worth it).

---

## Verified CLEAN
Bearer token only reaches httpx `headers=` — never logged / persisted / in `creds_ref` (which records only the auth KIND). `EXEC_ENVIRONMENTS` carries env-var **names**, not raw secrets; resolution is `os.environ.get` (no Secret Manager/file/URL → no SSRF/traversal in reference resolution). `_fetch_token`/`fetch_spec` are `_same_site`-gated (modulo EGRESS-01's port gap). Upload bytes are **inline base64** on the live path (not a filesystem path). Egress pinned per-run to the resolved `base_url`; `.lstrip("/")` neutralizes protocol-relative `//host`. The `RunnerEngine`/`BrowserDriver` Protocols + `_transport` seams are legit multi-caller test seams, not 1-impl abstractions.
