"""CloudProvider port — the cloud-estate reach the KGA tiers 5/6/7 duct-type (GCP today, swappable).

Importing this module pulls in nothing but stdlib, so the port is safe to reference from anywhere
(offline/test runs never touch a cloud SDK — those live behind each provider adapter, lazy-imported).
Provider-neutral modalities: platform is one of serverless / k8s / managed — never a vendor name."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

# Neutral platform categories (GCP Cloud Run·GKE·Cloud SQL == AWS Lambda·EKS·RDS == Azure Fn·AKS·SQL).
SERVERLESS = "serverless"
K8S = "k8s"
MANAGED = "managed"


@dataclass(frozen=True)
class ServiceRef:
    """One discovered deployed service in one env — the neutral discovery result + its provenance."""

    provider: str          # adapter name, e.g. "gcp"
    env: str               # env key within that provider's matrix, e.g. "prod"
    platform: str          # SERVERLESS | K8S | MANAGED
    name: str
    resource_path: str = ""   # full vendor resource id (provenance) — e.g. //run.../services/x
    live: float = 0.5         # 0..1 liveness ranking signal (recent activity); 0.5 = unknown

    @property
    def node_id(self) -> str:
        """Canonical graph id: cloudsvc:<provider>/<env>/<platform>/<name> (stable dedup key)."""
        return f"cloudsvc:{self.provider}/{self.env}/{self.platform}/{self.name}"


@dataclass
class LogEntry:
    """One RAW log line (unredacted — the neutral fetcher redacts). `outbound_host` is the Tier-7
    comms signal (an outbound HTTP host / gRPC authority / DB host the shared edge-derivation reads)."""

    severity: str = ""
    message: str = ""
    route: str = ""
    outbound_host: str = ""
    labels: list[str] = field(default_factory=list)


class CloudProvider(Protocol):
    """Read-only reach into one cloud estate. All construction of vendor SDK clients lives in the
    adapter (lazy), so this port is import-safe offline. Mirrors the ModelProvider/ObjectStore ports."""

    name: str

    def is_configured(self) -> bool:
        """True when this provider's SDK + credentials are available; False → the tier no-ops."""
        ...

    def env_keys(self) -> list[str]:
        """The env keys this provider knows (the discover producer iterates these)."""
        ...

    def discover(self, env_key: str) -> list[ServiceRef]:
        """Enumerate the deployed services in one env as neutral ServiceRefs (read-only)."""
        ...

    def read_logs(self, ref: ServiceRef, days: int, *, cap: int, min_severity: str = "WARNING") -> list[LogEntry]:
        """Read up to `cap` recent RAW log entries for `ref` over the last `days`. SYNC — the fetcher
        wraps this in asyncio.to_thread. Returns [] when the provider isn't configured."""
        ...
