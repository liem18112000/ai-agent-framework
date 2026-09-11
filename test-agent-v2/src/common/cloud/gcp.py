"""GcpCloudProvider — the GCP adapter for the CloudProvider port (Cloud Asset Inventory + Cloud
Logging + per-platform list fallback). Every google-cloud import is LAZY (inside a method), so the
base install and offline tests never touch it. Owns the GCP env matrix (KGA_GCP_ENV_MATRIX)."""

from __future__ import annotations

import json
import os
import pathlib
from dataclasses import dataclass, fields

from common.cloud.provider import K8S, MANAGED, SERVERLESS, LogEntry, ServiceRef
from common.monitoring import get_logger

log = get_logger("cloud.gcp")


@dataclass(frozen=True)
class Env:
    """The coordinates that locate one GCP environment. `project`+`region` are the minimum; `cluster`
    (GKE cluster name, its location = `region`) + `namespace` are needed for k8s discovery/log filters.
    Config-driven — see `GcpCloudProvider.env_matrix` (no values are compiled into source)."""

    project: str
    region: str
    cluster: str = ""
    namespace: str = ""


# No klara/vendor defaults in source — the real map is config (KGA_GCP_ENV_MATRIX / _FILE). Empty →
# the adapter has zero envs → discovery no-ops. A sample lives in deployments/gcp-env-matrix.example.json.
ENV_MATRIX: dict[str, Env] = {}

_ENV_FIELDS = tuple(f.name for f in fields(Env))


def _to_env(cfg) -> Env | None:
    """Build an `Env` from one config entry, keeping only known fields; None (skip) if it lacks the
    minimum project+region."""
    if not isinstance(cfg, dict):
        return None
    picked = {k: cfg[k] for k in _ENV_FIELDS if k in cfg}
    if not picked.get("project") or not picked.get("region"):
        return None
    return Env(**picked)


def _raw_config() -> str:
    """The raw env-matrix JSON — `KGA_GCP_ENV_MATRIX` (primary) else the file at
    `KGA_GCP_ENV_MATRIX_FILE`. Empty string when neither is set (a valid, off-by-default config)."""
    raw = os.environ.get("KGA_GCP_ENV_MATRIX", "").strip()
    if raw:
        return raw
    path = os.environ.get("KGA_GCP_ENV_MATRIX_FILE", "").strip()
    if not path:
        return ""
    try:
        return pathlib.Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        log.warning("KGA_GCP_ENV_MATRIX_FILE unreadable (%s); GCP explore has no envs", exc)
        return ""


def _load_matrix() -> dict[str, Env]:
    """Parse the env-matrix config into `{name: Env}`, skipping malformed/partial entries (each logged
    once). Any failure degrades to an empty map — never raised into the crawl."""
    raw = _raw_config()
    if not raw:
        return dict(ENV_MATRIX)  # empty by default
    try:
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 — a bad config must not break gather
        log.warning("GCP env matrix is not valid JSON (%s); GCP explore has no envs", exc)
        return dict(ENV_MATRIX)
    out: dict[str, Env] = {}
    for name, cfg in (data or {}).items():
        if name.startswith("_"):  # a "_comment"-style key (JSON has no comments) — skip silently
            continue
        if (env := _to_env(cfg)) is not None:
            out[name] = env
        else:
            log.warning("GCP env %r skipped: needs at least project+region (got %r)", name, cfg)
    return out

# CAI asset type -> neutral platform. Managed allow-list starts with the task-store + eventing the
# agents already use (§10 Q4); widen the map to widen scope, never a new branch.
_ASSET_PLATFORM = {
    "run.googleapis.com/Service": SERVERLESS,
    "container.googleapis.com/Cluster": K8S,
    "k8s.io/Deployment": K8S,
    "k8s.io/StatefulSet": K8S,
    "sqladmin.googleapis.com/Instance": MANAGED,
    "pubsub.googleapis.com/Topic": MANAGED,
    "redis.googleapis.com/Instance": MANAGED,
    "cloudtasks.googleapis.com/Queue": MANAGED,
}
_ASSET_TYPES = list(_ASSET_PLATFORM)


@dataclass
class _Clients:
    asset: object | None = None
    logging: object | None = None
    run: object | None = None
    container: object | None = None


class GcpCloudProvider:
    """CloudProvider adapter for GCP. Cheap to construct; clients built lazily on first reach."""

    name = "gcp"

    def __init__(self) -> None:
        self._clients: _Clients | None = None
        self._built = False
        self._matrix: dict[str, Env] | None = None

    # --- config -----------------------------------------------------------------------------------
    def env_matrix(self) -> dict[str, Env]:
        """The GCP env→coordinates map, config-driven (memoized so a bad config logs once, not per-env):
        `KGA_GCP_ENV_MATRIX` JSON (primary) else `KGA_GCP_ENV_MATRIX_FILE` (a mounted JSON file) else
        empty. `{name: {project, region, cluster?, namespace?}}`. Malformed/partial entries are skipped
        (logged once), never raised — empty is a valid config (the tier no-ops)."""
        if self._matrix is None:
            self._matrix = _load_matrix()
        return self._matrix

    def env_keys(self) -> list[str]:
        return list(self.env_matrix())

    def is_configured(self) -> bool:
        return self._get_clients() is not None

    # --- reach: discovery -------------------------------------------------------------------------
    def discover(self, env_key: str) -> list[ServiceRef]:
        clients = self._get_clients()
        env = self.env_matrix().get(env_key)
        if clients is None or env is None:
            return []
        if clients.asset is not None:
            try:
                return self._cai_discover(clients.asset, env_key, env)
            except Exception as exc:  # noqa: BLE001 — CAI not enabled / no scope -> per-platform fallback
                log.warning("gcp CAI discover failed for %s (%s); trying per-platform list", env_key, exc)
        return self._fallback_discover(clients, env_key, env)

    def _cai_discover(self, asset_client, env_key: str, env: Env) -> list[ServiceRef]:
        results = asset_client.search_all_resources(
            request={"scope": f"projects/{env.project}", "asset_types": _ASSET_TYPES})
        out: list[ServiceRef] = []
        for r in results:
            platform = _ASSET_PLATFORM.get(getattr(r, "asset_type", ""))
            if not platform:
                continue
            resource = getattr(r, "name", "") or ""
            out.append(ServiceRef(
                provider="gcp", env=env_key, platform=platform,
                name=_name_of(resource, getattr(r, "display_name", "")), resource_path=resource,
                live=_recency_live(getattr(r, "update_time", None))))
        return out

    def _fallback_discover(self, clients: _Clients, env_key: str, env: Env) -> list[ServiceRef]:
        out: list[ServiceRef] = []
        for platform, fn in ((SERVERLESS, self._list_run), (K8S, self._list_gke)):
            try:
                out += fn(clients, env_key, env)
            except Exception as exc:  # noqa: BLE001 — one platform failing must not kill the rest
                log.warning("gcp discover fallback %s/%s failed (%s)", env_key, platform, exc)
        return out

    def _list_run(self, clients: _Clients, env_key: str, env: Env) -> list[ServiceRef]:
        if clients.run is None:
            return []
        parent = f"projects/{env.project}/locations/{env.region}"
        return [ServiceRef(provider="gcp", env=env_key, platform=SERVERLESS,
                           name=_short(getattr(s, "name", "")), resource_path=getattr(s, "name", ""), live=1.0)
                for s in clients.run.list_services(parent=parent)]

    def _list_gke(self, clients: _Clients, env_key: str, env: Env) -> list[ServiceRef]:
        if clients.container is None:
            return []
        parent = f"projects/{env.project}/locations/{env.region}"
        resp = clients.container.list_clusters(parent=parent)
        return [ServiceRef(provider="gcp", env=env_key, platform=K8S, name=getattr(c, "name", ""),
                           resource_path=f"{parent}/clusters/{getattr(c, 'name', '')}", live=1.0)
                for c in getattr(resp, "clusters", []) or []]

    # --- reach: logs ------------------------------------------------------------------------------
    def read_logs(self, ref: ServiceRef, days: int, *, cap: int, min_severity: str = "WARNING") -> list[LogEntry]:
        clients = self._get_clients()
        env = self.env_matrix().get(ref.env)
        client = getattr(clients, "logging", None) if clients else None
        if client is None or env is None:
            return []
        import datetime as _dt  # lazy

        lower = (_dt.datetime.now(_dt.UTC) - _dt.timedelta(days=days)).isoformat()
        flt = _log_filter(env, ref.platform, ref.name, lower, min_severity)
        out: list[LogEntry] = []
        for entry in client.list_entries(filter_=flt, order_by="timestamp desc", max_results=cap):
            out.append(_entry_to_log(entry))
            if len(out) >= cap:
                break
        return out

    # --- lazy client factory (was common/gcp/factory.build_gcp_clients) ---------------------------
    def _get_clients(self) -> _Clients | None:
        if self._built:
            return self._clients
        self._built = True
        self._clients = _build_clients()
        return self._clients


def _build_clients() -> _Clients | None:
    """Read-only GCP clients from ADC, or None when the `gcp` extra is absent or creds unresolvable."""
    try:
        import google.auth  # part of every google-cloud lib; absent -> extra not installed
    except ImportError:
        return None
    try:
        google.auth.default()  # resolve ADC once; no creds -> degrade
    except Exception as exc:  # noqa: BLE001 — any creds failure (incl. DefaultCredentialsError) degrades
        log.info("GCP explore disabled: no Application Default Credentials (%s)", exc)
        return None
    clients = _Clients()
    for field_name, builder in (("asset", _asset_client), ("logging", _logging_client),
                                ("run", _run_client), ("container", _container_client)):
        try:
            setattr(clients, field_name, builder())
        except Exception as exc:  # noqa: BLE001 — one library missing must not kill the others
            log.info("GCP client %r unavailable (%s)", field_name, exc)
    if clients.asset is None and clients.run is None and clients.container is None:
        return None  # no discovery reach at all -> treat as unconfigured
    return clients


def _asset_client():
    from google.cloud import asset_v1

    return asset_v1.AssetServiceClient()


def _logging_client():
    from google.cloud import logging as gcp_logging

    return gcp_logging.Client()


def _run_client():
    from google.cloud import run_v2

    return run_v2.ServicesClient()


def _container_client():
    from google.cloud import container_v1

    return container_v1.ClusterManagerClient()


# --- pure helpers (no google import) --------------------------------------------------------------
def _name_of(resource: str, display_name: str = "") -> str:
    return display_name or _short(resource)


def _short(resource: str) -> str:
    return resource.rstrip("/").rsplit("/", 1)[-1] if resource else resource


def _recency_live(update_time) -> float:
    """Liveness from an asset's update time: recent (<=30d) -> 1.0, else 0.3, unknown -> 0.5."""
    if not update_time:
        return 0.5
    try:
        import datetime as _dt

        ts = update_time if isinstance(update_time, _dt.datetime) else _dt.datetime.fromisoformat(str(update_time))
        return 1.0 if (_dt.datetime.now(ts.tzinfo) - ts).days <= 30 else 0.3
    except Exception:  # noqa: BLE001 — a weird timestamp only drops liveness, not the asset
        return 0.5


def _log_filter(env: Env, platform: str, name: str, lower_ts: str, min_severity: str) -> str:
    """GCP Cloud Logging filter per neutral platform (reuses the org skills' resource filters)."""
    sev = f'severity>="{min_severity}" AND ' if min_severity else ""
    window = f'timestamp>="{lower_ts}"'
    if platform == SERVERLESS:
        return f'{sev}resource.type="cloud_run_revision" AND resource.labels.service_name="{name}" AND {window}'
    if platform == K8S:
        parts = [f'{sev}resource.type="k8s_container"', f'resource.labels.container_name="{name}"']
        if env.namespace:
            parts.append(f'resource.labels.namespace_name="{env.namespace}"')
        if env.cluster:  # target a specific GKE cluster (its location = env.region)
            parts.append(f'resource.labels.cluster_name="{env.cluster}"')
            parts.append(f'resource.labels.location="{env.region}"')
        return " AND ".join([*parts, window])
    return f'{sev}resource.labels.name="{name}" AND {window}'  # managed: resource-type-specific at X6


def _entry_to_log(entry) -> LogEntry:
    """Normalize a google-cloud-logging LogEntry -> neutral LogEntry (str textPayload or dict json)."""
    payload = getattr(entry, "payload", None)
    http = getattr(entry, "http_request", None) or {}
    if isinstance(payload, dict):
        message, host = str(payload.get("message", "")), str(payload.get("outbound_host", ""))
    else:
        message, host = str(payload or ""), ""
    return LogEntry(severity=str(getattr(entry, "severity", "") or ""), message=message,
                    route=http.get("requestUrl", "") if isinstance(http, dict) else "", outbound_host=host)
