"""Ports-and-adapters cloud reach — a swappable CloudProvider (GCP today; Azure/AWS = future adapters).

Provider-neutral: platform is serverless / k8s / managed, never a vendor name. The KGA tiers 5/6/7
duck-type this port; each adapter owns its SDK (lazy-imported) and its own env matrix."""

from common.cloud.config import cloud_configured, cloud_max_services, cloud_windows
from common.cloud.factory import cloud_providers
from common.cloud.gcp import GcpCloudProvider
from common.cloud.provider import K8S, MANAGED, SERVERLESS, CloudProvider, LogEntry, ServiceRef

__all__ = [
    "K8S", "MANAGED", "SERVERLESS",
    "CloudProvider", "GcpCloudProvider", "LogEntry", "ServiceRef",
    "cloud_configured", "cloud_max_services", "cloud_providers", "cloud_windows",
]
