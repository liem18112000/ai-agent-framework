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
from google.adk.tools import FunctionTool

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

# Read-only tools -- no confirmation needed.
_read_tools = [
    FunctionTool(list_clusters),
    FunctionTool(get_cluster),
    FunctionTool(list_node_pools),
    FunctionTool(list_pods),
    FunctionTool(get_pod_logs),
]

# Mutating tools -- ADK pauses for human confirmation before executing these.
_mutating_tools = [
    FunctionTool(resize_node_pool, require_confirmation=True),
    FunctionTool(restart_deployment, require_confirmation=True),
    FunctionTool(scale_deployment, require_confirmation=True),
]

root_agent = Agent(
    model="gemini-2.5-flash",
    name="devops_3f9a",
    description=(
        "GKE DevOps assistant for klara-nonprod/klara-performance/"
        "klara-infra/klara-repo. Never acts on klara-prod."
    ),
    instruction=agent_instruction,
    tools=_read_tools + _mutating_tools,
)
