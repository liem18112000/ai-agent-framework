"""X2 Tier-5 discover + X5 grounding-gated re-rank — `cloud_service_seeds` over a FakeCloudProvider
injected via the registry seam. Offline: no cloud SDK, no network."""

from __future__ import annotations

from common.cloud import K8S, SERVERLESS, ServiceRef
from knowledge_gathering.gather.explore.planners.schemas import CloudExplorePlan
from knowledge_gathering.gather.explore.seeds import cloud_discover
from knowledge_gathering.gather.explore.seeds.cloud_discover import (
    _rank,
    cloud_service_seeds,
    rerank_with_plan,
)
from tests.conftest import FakeCloudProvider


def _ref(env, name, platform=SERVERLESS, live=0.5):
    return ServiceRef(provider="fake", env=env, platform=platform, name=name,
                      resource_path=f"//x/{name}", live=live)


def _inject(monkeypatch, provider):
    monkeypatch.setattr(cloud_discover, "_providers", lambda: {"fake": provider})


async def test_discover_ranks_and_promotes(monkeypatch):
    refs = {"dev": [_ref("dev", "luz-thumbnail"), _ref("dev", "unrelated-worker")],
            "prod": [_ref("prod", "luz-thumbnail")]}
    _inject(monkeypatch, FakeCloudProvider(envs=("dev", "prod"), discover_fn=lambda e: refs[e]))
    seeds, md = await cloud_service_seeds("thumbnail export", cloud_max_services=8)

    assert seeds[0] == "cloudsvc:fake/prod/serverless/luz-thumbnail"   # term-match ∪ env-weight
    assert "cloudsvc:fake/dev/serverless/luz-thumbnail" in seeds
    assert "Cloud discover" in md


async def test_irrelevant_services_are_not_promoted(monkeypatch):
    """NOISE FIX: when no ticket token matches any service, promote NOTHING instead of filling the cap
    with arbitrary live services. Surfaces a transparent 'scanned N, none matched' note."""
    refs = [_ref("prod", "dev-luz-salary-calculation"), _ref("prod", "admin-agent"),
            _ref("dev", "message-broker")]
    _inject(monkeypatch, FakeCloudProvider(envs=("dev", "prod"), discover_fn=lambda e: refs))
    seeds, md = await cloud_service_seeds("zip import metadata health document", cloud_max_services=8)

    assert seeds == []                                   # nothing on-topic → nothing promoted (no noise)
    assert "none matched the ticket" in md               # transparent, not silent


async def test_relevant_subset_promoted_amid_noise(monkeypatch):
    """Only the ticket-relevant service is promoted out of a noisy estate (services sharing no ticket
    token are dropped)."""
    refs = [_ref("prod", "salary-calculation"), _ref("prod", "luz-docs-import"),
            _ref("prod", "antivirus-scanner")]
    _inject(monkeypatch, FakeCloudProvider(envs=("prod",), discover_fn=lambda e: refs))
    seeds, _md = await cloud_service_seeds("docs import zip", cloud_max_services=8)

    assert seeds == ["cloudsvc:fake/prod/serverless/luz-docs-import"]  # salary/antivirus dropped as noise


async def test_cap_respected_and_surfaced(monkeypatch):
    refs = [_ref("dev", f"svc-{i}") for i in range(10)]
    _inject(monkeypatch, FakeCloudProvider(envs=("dev",), discover_fn=lambda e: refs))
    seeds, md = await cloud_service_seeds("svc", cloud_max_services=3)

    assert len(seeds) == 3
    assert "capped at 3 of 10" in md                                    # no silent truncation


async def test_per_env_failure_isolated(monkeypatch):
    def discover(env_key):
        if env_key == "prod":
            raise RuntimeError("prod logs API disabled")
        return [_ref("dev", "luz-docs", platform=K8S)]

    _inject(monkeypatch, FakeCloudProvider(envs=("dev", "prod"), discover_fn=discover))
    seeds, _md = await cloud_service_seeds("docs", cloud_max_services=8)
    assert seeds == ["cloudsvc:fake/dev/k8s/luz-docs"]                  # dev survived prod's failure


async def test_unconfigured_provider_skipped(monkeypatch):
    _inject(monkeypatch, FakeCloudProvider(configured=False,
                                           discover_fn=lambda e: [_ref("dev", "x")]))
    seeds, md = await cloud_service_seeds("x")
    assert seeds == [] and md == ""


async def test_multi_provider_merges(monkeypatch):
    a = FakeCloudProvider("a", envs=("dev",), discover_fn=lambda e: [ServiceRef("a", "dev", K8S, "svc-a")])
    b = FakeCloudProvider("b", envs=("prod",), discover_fn=lambda e: [ServiceRef("b", "prod", K8S, "svc-b")])
    monkeypatch.setattr(cloud_discover, "_providers", lambda: {"a": a, "b": b})
    seeds, _ = await cloud_service_seeds("svc", cloud_max_services=8)
    assert set(seeds) == {"cloudsvc:a/dev/k8s/svc-a", "cloudsvc:b/prod/k8s/svc-b"}


# --- X5 grounding gate: rerank_with_plan only REORDERS discovered candidates ----------------------

def test_rerank_promotes_priority_hits_only():
    ranked = [_ref("prod", "worker-a"), _ref("prod", "luz-thumbnail"), _ref("prod", "worker-b")]
    out = rerank_with_plan(CloudExplorePlan(priority_services=["luz-thumbnail"]), ranked)
    assert out[0].name == "luz-thumbnail"
    assert {r.name for r in out} == {"worker-a", "luz-thumbnail", "worker-b"}   # nothing added/dropped


def test_rerank_cannot_add_unknown_service():
    ranked = [_ref("prod", "worker-a"), _ref("prod", "worker-b")]
    out = rerank_with_plan(CloudExplorePlan(priority_services=["ghost-not-discovered"]), ranked)
    assert [r.name for r in out] == ["worker-a", "worker-b"]            # hint matched nothing → no change


def test_rerank_empty_plan_is_identity():
    ranked = _rank([_ref("dev", "b"), _ref("dev", "a")], "")
    assert rerank_with_plan(CloudExplorePlan(), ranked) == ranked
