"""X0/X1 cloud-explore plumbing — neutral seed scheme, `_fetchable` gating, the CloudProvider port +
registry degrade, and the GCP adapter's env-matrix override. All offline (no cloud SDK installed)."""

from __future__ import annotations

import json

from common.cloud import (
    GcpCloudProvider,
    cloud_configured,
    cloud_max_services,
    cloud_providers,
    cloud_windows,
)
from common.cloud import gcp as gcp_adapter
from common.models import CLOUD_EDGE, CLOUD_SERVICE, Scope
from knowledge_gathering.gather.crawl.crawl import _fetchable
from knowledge_gathering.gather.crawl.fetch.base import NodeFetcher
from knowledge_gathering.gather.seed import normalize_seed

# --- X0: neutral seed grammar + fetchable gate ----------------------------------------------------

def test_cloudsvc_seed_is_identity():
    nid = "cloudsvc:gcp/prod/serverless/luz-thumbnail"
    assert normalize_seed(nid) == nid
    assert normalize_seed("cloudsvc:gcp/dev/k8s/luz-docs") == "cloudsvc:gcp/dev/k8s/luz-docs"


def test_non_cloudsvc_seeds_unchanged():
    assert normalize_seed("LUZ-158390") == "jira:LUZ-158390"
    assert normalize_seed("ws/repo") == "codegraph:ws/repo"


def test_fetchable_cloudsvc_gated_on_explore_cloud():
    nid = "cloudsvc:gcp/dev/k8s/luz-docs"
    assert _fetchable(nid, Scope()) is False
    assert _fetchable(nid, Scope(explore_cloud=True)) is True
    assert _fetchable(nid, Scope(follow_web=True)) is False           # independent of the web gate
    assert _fetchable("jira:LUZ-1", Scope(explore_cloud=True)) is True


def test_scope_defaults_are_off():
    s = Scope()
    assert s.explore_cloud is False and s.cloud_max_services == 8


def test_cloudsvc_fetcher_registered_and_neutral_kinds():
    assert "cloudsvc" in NodeFetcher.registry
    assert CLOUD_SERVICE == "cloud-service" and CLOUD_EDGE == "cloud-edge"


# --- X1: port + registry + adapter degrade + env matrix -------------------------------------------

def test_registry_default_is_gcp():
    providers = cloud_providers()
    assert set(providers) == {"gcp"}
    assert isinstance(providers["gcp"], GcpCloudProvider)
    assert providers["gcp"].name == "gcp"


def test_registry_selectable_and_skips_unknown(monkeypatch):
    monkeypatch.setenv("KGA_CLOUD_PROVIDERS", "gcp,azure")   # azure not registered → skipped, no error
    assert set(cloud_providers()) == {"gcp"}


def test_gcp_adapter_unconfigured_without_extra():
    # No `gcp` extra installed offline → no clients → not configured → discover/read_logs degrade to [].
    gcp = GcpCloudProvider()
    assert gcp.is_configured() is False
    assert gcp.discover("dev") == []


# --- config-driven env matrix (empty by default; env var / file; no klara values in source) --------

def test_env_matrix_empty_by_default_disables_tier(monkeypatch):
    # No config → zero envs → cloud_configured() False → discovery no-op + cloudsvc not fetchable.
    monkeypatch.delenv("KGA_GCP_ENV_MATRIX", raising=False)
    monkeypatch.delenv("KGA_GCP_ENV_MATRIX_FILE", raising=False)
    assert gcp_adapter.ENV_MATRIX == {}                      # no vendor defaults compiled in
    assert GcpCloudProvider().env_keys() == []
    assert cloud_configured() is False
    assert _fetchable("cloudsvc:gcp/dev/k8s/x", Scope(explore_cloud=cloud_configured())) is False


def test_env_matrix_from_json_parses_custom_cluster(monkeypatch):
    monkeypatch.setenv("KGA_GCP_ENV_MATRIX", json.dumps({
        "staging": {"project": "acme-nonprod", "region": "us-central1",
                    "cluster": "acme-staging-gke", "namespace": "stg"}}))
    env = GcpCloudProvider().env_matrix()["staging"]
    assert (env.project, env.region, env.cluster, env.namespace) == (
        "acme-nonprod", "us-central1", "acme-staging-gke", "stg")
    assert cloud_configured() is True                        # config present → tier enabled


def test_env_matrix_from_file_parses_same(monkeypatch, tmp_path):
    cfg = tmp_path / "matrix.json"
    cfg.write_text(json.dumps({
        "prod": {"project": "acme-prod", "region": "eu-west1",
                 "cluster": "acme-prod-gke", "namespace": "prod"}}), encoding="utf-8")
    monkeypatch.delenv("KGA_GCP_ENV_MATRIX", raising=False)
    monkeypatch.setenv("KGA_GCP_ENV_MATRIX_FILE", str(cfg))
    env = GcpCloudProvider().env_matrix()["prod"]
    assert (env.project, env.cluster, env.namespace) == ("acme-prod", "acme-prod-gke", "prod")


def test_env_matrix_partial_entry_skipped_not_raised(monkeypatch):
    monkeypatch.setenv("KGA_GCP_ENV_MATRIX", json.dumps({
        "good": {"project": "p", "region": "r"},
        "bad":  {"region": "r"},              # missing project → skipped, never raised
        "_comment": "ignored"}))
    assert set(GcpCloudProvider().env_keys()) == {"good"}


def test_env_matrix_malformed_json_degrades_to_empty(monkeypatch):
    monkeypatch.setenv("KGA_GCP_ENV_MATRIX", "{not valid json")
    assert GcpCloudProvider().env_keys() == []               # degrades, no crash


def test_neutral_flags_and_windows(monkeypatch):
    monkeypatch.setenv("KGA_CLOUD_MAX_SERVICES", "3")
    assert cloud_max_services() == 3
    monkeypatch.setenv("KGA_CLOUD_MAX_SERVICES", "notanint")
    assert cloud_max_services() == 8
    assert cloud_windows() == (7, 14, 21, 28)
    monkeypatch.setenv("KGA_CLOUD_WINDOWS", "1,2,3")
    assert cloud_windows() == (1, 2, 3)


def test_gcp_platform_mapping_is_neutral():
    # asset types map to neutral platform categories, never a vendor name.
    assert set(gcp_adapter._ASSET_PLATFORM.values()) <= {"serverless", "k8s", "managed"}
