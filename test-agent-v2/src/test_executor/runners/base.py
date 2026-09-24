"""Engine primitives shared by every runner: the result types, the engine Protocol, the per-run egress
allow-list, and the response-size cap."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from common.monitoring import get_logger

log = get_logger("exec.runners")

_MAX_RESPONSE_BYTES = 8 * 1024 * 1024  # cap a SUT response body read into RAM (OOM guard on the 2Gi agent)


def _same_site(url: str, base_url: str) -> bool:
    """Per-run egress allow-list: True iff `url` shares `base_url`'s exact http(s) ORIGIN
    (scheme + host + port). The executor legitimately targets INTERNAL / localhost test envs, so
    `common.net.host_blocked` (which blocks private/loopback) is the wrong guard here — the run must
    only reach its own base_url origin, which blocks metadata / file:// / foreign-host pivots AND
    same-host different-PORT pivots (e.g. a co-located docker/admin port) that scenario text could reach."""
    import httpx

    def _origin(x: str):
        try:
            u = httpx.URL(x)
        except Exception:  # noqa: BLE001 — a malformed URL has no valid origin
            return None
        if u.scheme not in ("http", "https") or not u.host:
            return None
        return (u.scheme, u.host, u.port or (443 if u.scheme == "https" else 80))

    o = _origin(url)
    return o is not None and o == _origin(base_url)


@dataclass
class StepOutcome:
    ok: bool
    message: str = ""      # failure detail (feeds triage) when not ok
    flaky: bool = False


@dataclass
class EngineResult:
    engine: str
    ran: bool                                        # False = unbound (no executable binding / no provider)
    outcomes: list[StepOutcome] = field(default_factory=list)
    note: str = ""

    @property
    def passed(self) -> bool:
        return self.ran and all(o.ok for o in self.outcomes)


class RunnerEngine(Protocol):
    name: str

    async def run(self, scenario: dict, *, base_url: str, auth: object = None,
                  spec: dict | None = None, path_vars: dict | None = None) -> EngineResult: ...
