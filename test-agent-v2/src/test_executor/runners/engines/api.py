"""ApiEngine — deterministic httpx execution against the run's base_url, with status/JSON conformance
and the Pillar-3 OpenAPI conformance oracle."""

from __future__ import annotations

import json

from test_executor.runners.base import (
    _MAX_RESPONSE_BYTES,
    EngineResult,
    StepOutcome,
    _same_site,
    log,
)
from test_executor.runners.translate import _send_kwargs, _subst_path


class ApiEngine:
    """Deterministic API execution: run the scenario's structured request against `base_url` and check
    conformance (status class + JSON validity). A scenario carries an executable binding under
    `request` = {method?, path, json?, expect_status?} (a future TPD or a translator attaches it);
    NL-only scenarios have none → unbound (route them to the LLM engine instead). httpx only, no browser."""

    name = "api"

    async def run(self, scenario: dict, *, base_url: str, auth: object = None,
                  spec: dict | None = None, path_vars: dict | None = None) -> EngineResult:
        req = scenario.get("request")
        if not (base_url and isinstance(req, dict) and req.get("path")):
            return EngineResult(self.name, ran=False,
                                note="no executable request binding (need OpenAPI/LLM) or no base_url")
        import httpx

        from test_executor import (
            runners,  # test seam: runners._transport (patched in tests), read at call time
        )
        method = str(req.get("method", "GET")).upper()
        path = _subst_path(str(req["path"]), path_vars)   # {tenant}/{id} → the env's path_vars values
        url = base_url.rstrip("/") + "/" + path.lstrip("/")
        where = f"{method} {req['path']}"  # host-free ledger label: keeps the PATH TEMPLATE, not the injected id
        if not _same_site(url, base_url):  # egress allow-list — the request must stay on the run's base_url host
            return EngineResult(self.name, ran=True, outcomes=[StepOutcome(False, f"{where}: blocked off-site target")])
        expect = int(req.get("expect_status", 0))
        outcomes: list[StepOutcome] = []
        try:
            headers = getattr(auth, "headers", None) or None   # AuthContext.headers (bearer), if any
            async with httpx.AsyncClient(timeout=30, transport=runners._transport) as client, \
                    client.stream(method, url, headers=headers, **_send_kwargs(req)) as resp:
                declared = resp.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > _MAX_RESPONSE_BYTES:
                    return EngineResult(self.name, ran=True, outcomes=[StepOutcome(
                        False, f"{where}: response exceeds {_MAX_RESPONSE_BYTES} bytes")])
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) > _MAX_RESPONSE_BYTES:  # cap before the body OOMs the 2Gi container
                        return EngineResult(self.name, ran=True, outcomes=[StepOutcome(
                            False, f"{where}: response exceeds {_MAX_RESPONSE_BYTES} bytes")])
                text = bytes(body).decode(resp.charset_encoding or "utf-8", errors="replace")
                status, ctype = resp.status_code, resp.headers.get("content-type", "")
        except Exception as exc:  # noqa: BLE001 — a transport failure is a real (Environment) failure to triage
            log.warning("exec api %s failed: %s", where, exc)  # full detail server-side only
            return EngineResult(self.name, ran=True,
                                outcomes=[StepOutcome(False, f"{where}: request failed ({type(exc).__name__})")])
        # status conformance: an explicit expect wins; else any non-5xx is acceptable EXCEPT an
        # unexpected 401/403 — those are never a pass (a broken-creds run must fail, not report green).
        ok_status = (status == expect) if expect else (status < 500 and status not in (401, 403))
        outcomes.append(StepOutcome(ok_status,
                        "" if ok_status else f"{where}: status {status} (expected {expect or '<500, authorized'})"))
        # content conformance: a JSON content-type must parse
        if "json" in ctype:
            try:
                json.loads(text)
            except ValueError:
                outcomes.append(StepOutcome(False, f"{where}: malformed JSON body"))
        # oracle: the expected end-state must appear in the response (the scenario's `Then`)
        want = str(req.get("expect_contains", ""))
        if want and want not in text:
            outcomes.append(StepOutcome(False, f"{where}: response missing expected {want!r}"))
        # Pillar 3: OpenAPI conformance oracle — status + response-schema declared by the spec
        if isinstance(spec, dict) and spec.get("spec"):
            from test_executor.openapi import conformance_failures, match_operation
            op = match_operation(spec.get("ops") or [], method, path.split("?", 1)[0])
            if op is not None:
                for msg in conformance_failures(spec["spec"], op, status=status, body_text=text, content_type=ctype):
                    outcomes.append(StepOutcome(False, f"{where}: {msg}"))
        return EngineResult(self.name, ran=True, outcomes=outcomes)
