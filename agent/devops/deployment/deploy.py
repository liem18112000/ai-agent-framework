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

"""Deploys (or updates) devops-3f9a to Vertex AI Agent Engine.

Usage:
    python deployment/deploy.py                 # create a new engine
    python deployment/deploy.py --update RESOURCE_NAME   # update in place
"""

import argparse
import tomllib
from pathlib import Path

import vertexai
from vertexai import agent_engines
from vertexai.preview import reasoning_engines

from devops_3f9a.agent import root_agent
from mcp_bridge.config import LOCATION, PROJECT_ID

STAGING_BUCKET = "gs://klara-nonprod-agent-engine-staging-us-central1"

_PYPROJECT = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text())
REQUIREMENTS = _PYPROJECT["project"]["dependencies"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--update",
        dest="resource_name",
        default=None,
        help="Existing reasoningEngines resource name to update in place, "
        "instead of creating a new one.",
    )
    args = parser.parse_args()

    vertexai.init(project=PROJECT_ID, location=LOCATION, staging_bucket=STAGING_BUCKET)

    app = reasoning_engines.AdkApp(agent=root_agent, enable_tracing=True)

    kwargs = dict(
        requirements=REQUIREMENTS,
        extra_packages=["./devops_3f9a"],
        display_name="devops-3f9a",
        description=(
            "GKE DevOps assistant for klara-nonprod/klara-performance/"
            "klara-infra/klara-repo (never klara-prod). Read tools + "
            "confirmation-gated mutating tools (resize node pool, restart "
            "deployment, scale deployment)."
        ),
        env_vars={
            "NUM_WORKERS": "1",
            "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "true",
        },
    )

    if args.resource_name:
        remote_app = agent_engines.update(
            resource_name=args.resource_name, agent_engine=app, **kwargs
        )
        print("UPDATED:", remote_app.resource_name)
    else:
        remote_app = agent_engines.create(app, **kwargs)
        print("CREATED:", remote_app.resource_name)


if __name__ == "__main__":
    main()
