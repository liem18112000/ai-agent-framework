"""X3 Tier-6 (expanding-window logs + distill + REDACT) & X4 Tier-7 (grounded/demoted edges).

Offline: a FakeCloudProvider (injected via the registry seam) returns canned LogEntry lists per `days`;
no cloud SDK, no network."""

from __future__ import annotations

import pytest

from common.cloud import LogEntry
from common.models import CLOUD_EDGE, CLOUD_SERVICE, Scope
from knowledge_gathering.gather.crawl.fetch import cloud_service
from tests.conftest import FakeCloudProvider

_FETCHER = cloud_service.CloudServiceFetcher()
_SCOPE = Scope(explore_cloud=True)


def _inject(monkeypatch, *, read_logs_fn, configured=True):
    provider = FakeCloudProvider("fake", read_logs_fn=read_logs_fn, configured=configured)
    monkeypatch.setattr(cloud_service, "_providers", lambda: {"fake": provider})


def _entry(severity="INFO", message="ok", route="", host=""):
    return LogEntry(severity=severity, message=message, route=route, outbound_host=host)


async def test_window_widens_until_enough(monkeypatch):
    seen_days: list[int] = []

    def read_logs(ref, days, cap, min_severity):
        seen_days.append(days)
        if days < 28:
            return [_entry(route="/health")]                       # 0 sigs, 0 deps, 1 entry → widen
        # 3 DISTINCT signatures (non-numeric; _signature normalizes digits away → would collapse)
        return [_entry("ERROR", m) for m in ("null pointer", "read timeout", "quota exceeded")]

    _inject(monkeypatch, read_logs_fn=read_logs)
    _links, note, text = await _FETCHER.fetch(None, "fake/dev/k8s/orders", "cloudsvc:fake/dev/k8s/orders", _SCOPE)

    assert seen_days == [7, 14, 21, 28]          # widened through every window
    assert note.type == CLOUD_SERVICE
    assert "[window: 28d;" in note.synopsis and "SHORTFALL" not in note.synopsis
    assert text == ""                            # nothing raw persisted


async def test_secret_is_redacted(monkeypatch):
    def read_logs(ref, days, cap, min_severity):
        return [_entry("ERROR", "login failed password=hunter2 token=deadbeefcafebabe0123"),
                _entry("ERROR", "db error host=x"), _entry("ERROR", "timeout waiting")]

    _inject(monkeypatch, read_logs_fn=read_logs)
    _, note, _ = await _FETCHER.fetch(None, "fake/dev/serverless/api", "cloudsvc:fake/dev/serverless/api", _SCOPE)

    assert "hunter2" not in note.synopsis and "deadbeefcafebabe0123" not in note.synopsis
    assert "[REDACTED]" in note.synopsis and "Health:" in note.synopsis


async def test_shortfall_recorded_when_never_enough(monkeypatch):
    _inject(monkeypatch, read_logs_fn=lambda ref, days, cap, ms: [_entry(route="/only")])
    _, note, _ = await _FETCHER.fetch(None, "fake/dev/serverless/api", "cloudsvc:fake/dev/serverless/api", _SCOPE)
    assert "SHORTFALL" in note.synopsis and "28d" in note.synopsis


async def test_entry_cap_and_severity_passed_through(monkeypatch):
    seen: list[tuple] = []

    def read_logs(ref, days, cap, min_severity):
        seen.append((cap, min_severity))
        return [_entry("ERROR", f"e{c}") for c in "abc"]

    _inject(monkeypatch, read_logs_fn=read_logs)
    await _FETCHER.fetch(None, "fake/dev/serverless/api", "cloudsvc:fake/dev/serverless/api", _SCOPE)
    assert seen and all(cap == cloud_service._MAX_ENTRIES and ms == "WARNING" for cap, ms in seen)


# --- X4 Tier-7 edges: grounded (in_scope) vs unconfirmed (demoted) --------------------------------

async def test_edges_grounded_and_demoted(monkeypatch):
    def read_logs(ref, days, cap, min_severity):
        return [_entry(host="luz-docs.dev.svc.cluster.local"),   # k8s DNS → grounded
                _entry(host="api.external.com")]                 # not a service → demoted

    _inject(monkeypatch, read_logs_fn=read_logs)
    links, note, _ = await _FETCHER.fetch(None, "fake/dev/serverless/orders", "cloudsvc:fake/dev/serverless/orders", _SCOPE)

    by_target = {lr.canonical_url: lr for lr in links}
    grounded = by_target["cloudsvc:fake/dev/k8s/luz-docs"]
    assert grounded.type == CLOUD_EDGE and grounded.origin == "cloud-log"
    assert grounded.in_scope is True and grounded.source_id == "cloudsvc:fake/dev/serverless/orders"

    assert by_target["cloudext:api.external.com"].in_scope is False   # unconfirmed, recorded-only
    assert note.links == links


async def test_unconfigured_provider_fetch_raises(monkeypatch):
    _inject(monkeypatch, read_logs_fn=lambda ref, days, cap, ms: [], configured=False)
    with pytest.raises(RuntimeError, match="cloud provider not configured"):
        await _FETCHER.fetch(None, "fake/dev/serverless/api", "cloudsvc:fake/dev/serverless/api", _SCOPE)


async def test_unknown_provider_fetch_raises(monkeypatch):
    monkeypatch.setattr(cloud_service, "_providers", dict)
    with pytest.raises(RuntimeError, match="not configured"):
        await _FETCHER.fetch(None, "ghost/dev/serverless/api", "cloudsvc:ghost/dev/serverless/api", _SCOPE)


async def test_malformed_ident_raises(monkeypatch):
    _inject(monkeypatch, read_logs_fn=lambda ref, days, cap, ms: [])
    with pytest.raises(ValueError, match="malformed cloudsvc"):
        await _FETCHER.fetch(None, "fake/dev/serverless", "cloudsvc:fake/dev/serverless", _SCOPE)
