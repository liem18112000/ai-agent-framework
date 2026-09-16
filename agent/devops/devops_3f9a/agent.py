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

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools import FunctionTool
from google.adk.tools.retrieval.vertex_ai_rag_retrieval import VertexAiRagRetrieval

from .prompt import agent_instruction
from .tools.gke_tools import (
    get_cluster,
    get_pod_logs,
    list_clusters,
    list_node_pools,
    list_pods,
    resize_node_pool,
    restart_deployment,
    scale_deployment,
)

# Production RAG corpus of LUZ ops repo docs (agent docs, gcp-* domain
# runbooks, terraform/kustomize READMEs) -- Scaled-tier backend, docs
# parsed with an LLM parser (not naive text-splitting) for better
# retrieval over tables/structure. See agent/devops/RAG.md for how this
# corpus was built and how to refresh it.
_RAG_CORPUS = (
    "projects/335505349498/locations/europe-west6/ragCorpora/5148740273991319552"
)

_ops_docs_retrieval = VertexAiRagRetrieval(
    name="search_ops_docs",
    description=(
        "Searches the LUZ ops repo's documentation -- this agent's own "
        "README/DEPLOY docs, GCP domain runbooks (GKE, IAM, network, "
        "secrets, observability, pubsub, GCS, Cloud Run), and "
        "terraform/kustomize READMEs across the ops estate. Use this to "
        "answer questions about naming conventions, setup steps, or "
        "cluster/service context instead of guessing."
    ),
    rag_corpora=[_RAG_CORPUS],
    similarity_top_k=5,
    vector_distance_threshold=0.5,
)

# Read-only tools -- no confirmation needed.
_read_tools = [
    FunctionTool(list_clusters),
    FunctionTool(get_cluster),
    FunctionTool(list_node_pools),
    FunctionTool(list_pods),
    FunctionTool(get_pod_logs),
    _ops_docs_retrieval,
]

# Mutating tools -- ADK pauses for human confirmation before executing these.
_mutating_tools = [
    FunctionTool(resize_node_pool, require_confirmation=True),
    FunctionTool(restart_deployment, require_confirmation=True),
    FunctionTool(scale_deployment, require_confirmation=True),
]

# The GCP project this agent is deployed into (matches mcp_bridge/config.py's
# PROJECT_ID -- not imported from there since mcp_bridge isn't packaged into
# the deployed Agent Engine container; see deployment/deploy.py's
# extra_packages).
_DEPLOY_PROJECT_ID = "klara-nonprod"

root_agent = Agent(
    model=LiteLlm(
        model="vertex_ai/claude-sonnet-5",
        vertex_project=_DEPLOY_PROJECT_ID,
        # Claude on Vertex AI Model Garden is served from "global", not the
        # us-central1 region this agent itself deploys into.
        vertex_location="global",
    ),
    name="devops_3f9a",
    description=(
        "GKE DevOps assistant for klara-nonprod/klara-performance/"
        "klara-infra/klara-repo. Never acts on klara-prod."
    ),
    instruction=agent_instruction,
    tools=_read_tools + _mutating_tools,
)
