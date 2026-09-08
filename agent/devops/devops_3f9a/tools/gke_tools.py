# Copyright 2026 LUZ Ops
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""GKE tools for the devops-3f9a agent.

Two layers, matching two different GCP access paths:

1. Cluster / node-pool level -- via the GKE Container API
   (container.googleapis.com through google.cloud.container_v1). This is a
   public, global API: it works regardless of whether a cluster's control
   plane uses a private endpoint, because you're calling Google's control
   plane API, not the cluster's own Kubernetes API server directly.

2. Pod / deployment level -- via the Kubernetes API of the target cluster
   itself, using the `kubernetes` Python client with a bearer token minted
   from this agent's own GCP credentials. This DOES require network
   reachability from wherever this agent runs to each cluster's control
   plane endpoint, and a matching Kubernetes RBAC binding for this agent's
   service account inside that cluster. See devops-3f9a/README.md
   "Prerequisites" for the one-time per-cluster setup this needs -- if that
   setup hasn't been done for a cluster, these tools will surface a clear
   connection/RBAC error rather than silently failing.
"""

from __future__ import annotations

import base64
import tempfile
from typing import Optional

import google.auth
import google.auth.transport.requests
from google.cloud import container_v1
from kubernetes import client as k8s_client

from ..config import assert_project_allowed

_container_client: Optional[container_v1.ClusterManagerClient] = None


def _get_container_client() -> container_v1.ClusterManagerClient:
    global _container_client
    if _container_client is None:
        _container_client = container_v1.ClusterManagerClient()
    return _container_client


# --------------------------------------------------------------------------
# Cluster / node-pool level tools (Container API -- always reachable)
# --------------------------------------------------------------------------


def list_clusters(project_id: str) -> dict:
    """Lists GKE clusters in a project.

    Args:
        project_id: The GCP project ID. Must be one of the allowed projects
            for this agent (klara-nonprod, klara-performance, klara-infra,
            klara-repo). klara-prod is never allowed.

    Returns:
        A dict with a "clusters" list, each entry having name, location,
        status, current_node_count, and initial_cluster_version.
    """
    assert_project_allowed(project_id)
    client = _get_container_client()
    parent = f"projects/{project_id}/locations/-"
    resp = client.list_clusters(parent=parent)
    return {
        "clusters": [
            {
                "name": c.name,
                "location": c.location,
                "status": c.status.name,
                "current_node_count": c.current_node_count,
                "initial_cluster_version": c.initial_cluster_version,
                "endpoint": c.endpoint,
                "private_cluster": c.private_cluster_config.enable_private_nodes
                if c.private_cluster_config
                else False,
            }
            for c in resp.clusters
        ]
    }


def get_cluster(project_id: str, location: str, cluster_id: str) -> dict:
    """Gets details and current status for one GKE cluster.

    Args:
        project_id: The GCP project ID (must be in the allowed scope).
        location: The cluster's region or zone (e.g. "europe-west6" or
            "europe-west6-a").
        cluster_id: The cluster's name.
    """
    assert_project_allowed(project_id)
    client = _get_container_client()
    name = f"projects/{project_id}/locations/{location}/clusters/{cluster_id}"
    c = client.get_cluster(name=name)
    return {
        "name": c.name,
        "status": c.status.name,
        "current_node_count": c.current_node_count,
        "node_pools": [np.name for np in c.node_pools],
        "current_master_version": c.current_master_version,
        "network": c.network,
        "subnetwork": c.subnetwork,
    }


def list_node_pools(project_id: str, location: str, cluster_id: str) -> dict:
    """Lists node pools in a GKE cluster with their current size and machine type."""
    assert_project_allowed(project_id)
    client = _get_container_client()
    parent = f"projects/{project_id}/locations/{location}/clusters/{cluster_id}"
    resp = client.list_node_pools(parent=parent)
    return {
        "node_pools": [
            {
                "name": np.name,
                "status": np.status.name,
                "initial_node_count": np.initial_node_count,
                "machine_type": np.config.machine_type if np.config else None,
                "autoscaling_enabled": np.autoscaling.enabled
                if np.autoscaling
                else False,
                "min_node_count": np.autoscaling.min_node_count
                if np.autoscaling
                else None,
                "max_node_count": np.autoscaling.max_node_count
                if np.autoscaling
                else None,
            }
            for np in resp.node_pools
        ]
    }


def resize_node_pool(
    project_id: str, location: str, cluster_id: str, node_pool_id: str, node_count: int
) -> dict:
    """Resizes a GKE node pool to an exact node count. MUTATING -- requires confirmation.

    Args:
        project_id: The GCP project ID (must be in the allowed scope).
        location: The cluster's region or zone.
        cluster_id: The cluster's name.
        node_pool_id: The node pool to resize.
        node_count: The target node count (per zone, for zonal node pools).
    """
    assert_project_allowed(project_id)
    client = _get_container_client()
    name = (
        f"projects/{project_id}/locations/{location}/clusters/{cluster_id}"
        f"/nodePools/{node_pool_id}"
    )
    op = client.set_node_pool_size(name=name, node_count=node_count)
    return {
        "operation_name": op.name,
        "operation_status": op.status.name,
        "requested_node_count": node_count,
    }


# --------------------------------------------------------------------------
# Pod / deployment level tools (Kubernetes API -- needs network path + RBAC)
# --------------------------------------------------------------------------


def _build_k8s_api_client(
    project_id: str, location: str, cluster_id: str
) -> k8s_client.ApiClient:
    assert_project_allowed(project_id)
    container_client = _get_container_client()
    name = f"projects/{project_id}/locations/{location}/clusters/{cluster_id}"
    cluster = container_client.get_cluster(name=name)

    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    creds.refresh(google.auth.transport.requests.Request())

    ca_cert_path = tempfile.NamedTemporaryFile(delete=False, suffix=".pem").name
    with open(ca_cert_path, "wb") as f:
        f.write(base64.b64decode(cluster.master_auth.cluster_ca_certificate))

    configuration = k8s_client.Configuration()
    configuration.host = f"https://{cluster.endpoint}"
    configuration.api_key["authorization"] = creds.token
    configuration.api_key_prefix["authorization"] = "Bearer"
    configuration.ssl_ca_cert = ca_cert_path

    return k8s_client.ApiClient(configuration)


def list_pods(
    project_id: str, location: str, cluster_id: str, namespace: str = "default"
) -> dict:
    """Lists pods in a namespace of a GKE cluster.

    Requires this agent's service account to have network reachability to
    the cluster's control plane and a Kubernetes RBAC binding granting at
    least read access -- see README "Prerequisites".
    """
    api_client = _build_k8s_api_client(project_id, location, cluster_id)
    core_v1 = k8s_client.CoreV1Api(api_client)
    pods = core_v1.list_namespaced_pod(namespace=namespace)
    return {
        "pods": [
            {
                "name": p.metadata.name,
                "phase": p.status.phase,
                "ready": all(
                    cs.ready for cs in (p.status.container_statuses or [])
                ),
                "restarts": sum(
                    cs.restart_count for cs in (p.status.container_statuses or [])
                ),
                "node": p.spec.node_name,
            }
            for p in pods.items
        ]
    }


def get_pod_logs(
    project_id: str,
    location: str,
    cluster_id: str,
    namespace: str,
    pod_name: str,
    container: Optional[str] = None,
    tail_lines: int = 200,
) -> dict:
    """Fetches the tail of a pod's logs."""
    api_client = _build_k8s_api_client(project_id, location, cluster_id)
    core_v1 = k8s_client.CoreV1Api(api_client)
    logs = core_v1.read_namespaced_pod_log(
        name=pod_name,
        namespace=namespace,
        container=container,
        tail_lines=tail_lines,
    )
    return {"pod": pod_name, "logs": logs}


def restart_deployment(
    project_id: str, location: str, cluster_id: str, namespace: str, deployment_name: str
) -> dict:
    """Triggers a rolling restart of a Deployment (equivalent to
    `kubectl rollout restart`). MUTATING -- requires confirmation.
    """
    import datetime

    api_client = _build_k8s_api_client(project_id, location, cluster_id)
    apps_v1 = k8s_client.AppsV1Api(api_client)
    now = datetime.datetime.utcnow().isoformat() + "Z"
    patch = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {"kubectl.kubernetes.io/restartedAt": now}
                }
            }
        }
    }
    apps_v1.patch_namespaced_deployment(
        name=deployment_name, namespace=namespace, body=patch
    )
    return {"deployment": deployment_name, "namespace": namespace, "restarted_at": now}


def scale_deployment(
    project_id: str,
    location: str,
    cluster_id: str,
    namespace: str,
    deployment_name: str,
    replicas: int,
) -> dict:
    """Scales a Deployment to an exact replica count. MUTATING -- requires confirmation."""
    api_client = _build_k8s_api_client(project_id, location, cluster_id)
    apps_v1 = k8s_client.AppsV1Api(api_client)
    apps_v1.patch_namespaced_deployment_scale(
        name=deployment_name,
        namespace=namespace,
        body={"spec": {"replicas": replicas}},
    )
    return {"deployment": deployment_name, "namespace": namespace, "replicas": replicas}
