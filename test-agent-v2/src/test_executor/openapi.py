"""OpenAPI grounding for the API engine (Pillar 3): the target's spec is both the request GENERATOR
(the LLM picks a REAL operation instead of inventing a path) and the response ORACLE (status +
schema conformance). No property-based fuzzer here — plain spec parsing + jsonschema, so it needs no
heavy dep. Schemathesis-style fuzzing is a future optional extra.

A spec is fetched once per run from the environment's `spec_url` (e.g. Spring's `/v3/api-docs`),
same-host-gated like every other request. Best-effort throughout: any parse/validation failure logs
and degrades (no spec → the LLM falls back to its ungrounded guess; bad schema → no conformance check).
"""

from __future__ import annotations

import json

from common.monitoring import get_logger

log = get_logger("exec.openapi")

_METHODS = ("get", "post", "put", "patch", "delete")
_MAX_SPEC_BYTES = 8 * 1024 * 1024  # cap the (untrusted SUT) OpenAPI spec body read into RAM (OOM guard)


async def fetch_spec(spec_url: str, *, base_url: str, headers: dict | None = None) -> dict | None:
    """GET + parse the OpenAPI spec (JSON or YAML). `spec_url` may be a path (joined to base_url) or an
    absolute same-host URL. Returns the parsed dict, or None on any failure (→ ungrounded fallback)."""
    import httpx

    from test_executor.runners import _same_site
    url = str(httpx.URL(base_url).join(spec_url))
    if not _same_site(url, base_url):
        log.warning("spec_url %r is off-site for base_url — refusing to fetch", spec_url)
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as client, \
                client.stream("GET", url, headers=headers or None) as resp:
            resp.raise_for_status()
            body = bytearray()
            async for chunk in resp.aiter_bytes():
                body += chunk
                if len(body) > _MAX_SPEC_BYTES:  # a SUT spec is untrusted → cap before it OOMs the 2Gi agent
                    log.warning("spec %s exceeds %d bytes — skipping grounding", spec_url, _MAX_SPEC_BYTES)
                    return None
            text = bytes(body).decode(resp.charset_encoding or "utf-8", errors="replace")
        try:
            return json.loads(text)
        except ValueError:
            import yaml
            # ponytail: safe_load blocks code exec but not YAML anchor bombs; the byte cap bounds the input
            return yaml.safe_load(text)
    except Exception as exc:  # noqa: BLE001 — no spec is a soft failure (ungrounded fallback), never a crash
        log.warning("fetch_spec(%s) failed: %s", spec_url, type(exc).__name__)
        return None


def parse_operations(spec: dict) -> list[dict]:
    """Flatten `spec.paths` → `[{method, path, summary, op}]` for the real operations the target exposes."""
    out: list[dict] = []
    for path, item in (spec.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method.lower() in _METHODS and isinstance(op, dict):
                out.append({"method": method.upper(), "path": path,
                            "summary": op.get("summary") or op.get("operationId") or "", "op": op})
    return out


def operation_catalog(ops: list[dict], *, limit: int = 60) -> str:
    """A compact `METHOD path — summary` list to ground the LLM's translation on real endpoints."""
    return "\n".join(f"{o['method']} {o['path']} — {o['summary']}" for o in ops[:limit])


def _path_matches(template: str, actual: str) -> bool:
    """True if a concrete `actual` path matches an OpenAPI `template` (…/{id}/… segments are wildcards)."""
    t, a = template.strip("/").split("/"), actual.strip("/").split("/")
    if len(t) != len(a):
        return False
    return all(seg.startswith("{") and seg.endswith("}") or seg == a[i] for i, seg in enumerate(t))


def match_operation(ops: list[dict], method: str, path: str) -> dict | None:
    """Find the spec operation for a concrete request (exact path first, then a templated match)."""
    method = method.upper()
    path = path.split("?", 1)[0]
    for o in ops:
        if o["method"] == method and o["path"] == path:
            return o
    for o in ops:
        if o["method"] == method and _path_matches(o["path"], path):
            return o
    return None


def _response_schema(op: dict, status: int, spec: dict) -> dict | None:
    """The declared JSON response schema for `status` (or the 2xx / default), if any."""
    responses = op.get("op", {}).get("responses", {}) or {}
    key = next((k for k in (str(status), f"{status // 100}XX", f"{status // 100}xx", "default") if k in responses), None)
    body = responses.get(key) if key else None
    content = (body or {}).get("content", {}) if isinstance(body, dict) else {}
    for ctype, media in content.items():
        if "json" in ctype and isinstance(media, dict) and media.get("schema"):
            return media["schema"]
    return None


def conformance_failures(spec: dict, op: dict, *, status: int, body_text: str, content_type: str) -> list[str]:
    """Pillar-3 oracle: status-code + response-schema conformance against the spec. Returns failure
    messages (empty = conforms). Best-effort — a validator error degrades to no schema check, not a crash."""
    fails: list[str] = []
    responses = op.get("op", {}).get("responses", {}) or {}
    declared = {str(k) for k in responses}
    if declared:
        ok = (str(status) in declared or f"{status // 100}XX" in declared
              or f"{status // 100}xx" in declared or "default" in responses)
        if not ok:
            fails.append(f"status {status} not declared in the spec (declared: {sorted(declared)})")
    schema = _response_schema(op, status, spec)
    if schema and "json" in content_type:
        try:
            import jsonschema
            from jsonschema.validators import Draft7Validator, RefResolver
            body = json.loads(body_text)

            def _no_remote(uri):  # SINK-01: a tampered SUT spec must not fetch http(s)/file:// $refs
                raise RuntimeError(f"remote $ref blocked: {uri}")  # (SSRF / local-file read); #/... refs still work

            resolver = RefResolver.from_schema(spec)
            resolver.resolve_remote = _no_remote
            Draft7Validator(schema, resolver=resolver).validate(body)
        except jsonschema.ValidationError as exc:
            fails.append(f"response body does not conform to the declared schema ({exc.message[:120]})")
        except Exception as exc:  # noqa: BLE001 — validator/ref-resolution issue → skip the schema check
            log.warning("conformance schema check skipped: %s", type(exc).__name__)
    return fails
