"""OpenAPI spec READING — framework-neutral, no I/O, no agent dependencies.

Lives in `common` because BOTH agents need it and the agents must never import each other: the executor
grounds requests + judges conformance against a spec (`test_executor.oracle`), and TPD generates
spec-driven conformance scenarios from one (`test_plan_definition.implement.generate.scenarios`).

Only pure parsing lives here. FETCHING a spec (needs the run's egress allow-list) and JUDGING a response
against it (the conformance oracle) stay in `test_executor.oracle` — they are execution concerns.
"""

from __future__ import annotations

from dataclasses import dataclass

_METHODS = ("get", "post", "put", "patch", "delete")


@dataclass(frozen=True)
class Operation:
    """One OpenAPI operation the target exposes — its `METHOD path` identity plus the raw spec `op`
    object (responses / parameters / requestBody) the conformance oracle reads."""

    method: str
    path: str
    summary: str
    op: dict

    @property
    def declared_statuses(self) -> set[str]:
        """The response status codes this operation DECLARES — the contract a conformance test asserts."""
        return {str(k) for k in (self.op.get("responses") or {})}

    @property
    def path_templates(self) -> list[str]:
        """The `{param}` segments in the path (e.g. ['{tenant-id}', '{id}']) — what must be filled in."""
        return [s for s in self.path.split("/") if s.startswith("{") and s.endswith("}")]


def parse_operations(spec: dict) -> list[Operation]:
    """Flatten `spec.paths` → the real `Operation`s the target exposes."""
    out: list[Operation] = []
    for path, item in (spec.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method.lower() in _METHODS and isinstance(op, dict):
                out.append(Operation(method=method.upper(), path=path,
                                     summary=op.get("summary") or op.get("operationId") or "", op=op))
    return out


def operation_catalog(ops: list[Operation], *, limit: int = 60) -> str:
    """A compact `METHOD path — summary` list to ground the LLM's translation on real endpoints."""
    return "\n".join(f"{o.method} {o.path} — {o.summary}" for o in ops[:limit])


def _path_matches(template: str, actual: str) -> bool:
    """True if a concrete `actual` path matches an OpenAPI `template` (…/{id}/… segments are wildcards)."""
    t, a = template.strip("/").split("/"), actual.strip("/").split("/")
    if len(t) != len(a):
        return False
    return all(seg.startswith("{") and seg.endswith("}") or seg == a[i] for i, seg in enumerate(t))


def match_operation(ops: list[Operation], method: str, path: str) -> Operation | None:
    """Find the spec operation for a concrete request (exact path first, then a templated match)."""
    method = method.upper()
    path = path.split("?", 1)[0]
    for o in ops:
        if o.method == method and o.path == path:
            return o
    for o in ops:
        if o.method == method and _path_matches(o.path, path):
            return o
    return None
