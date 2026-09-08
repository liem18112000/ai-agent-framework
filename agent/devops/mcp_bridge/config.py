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

"""Deployment coordinates for the devops-3f9a Agent Engine, shared by
vertex_worker.py, server.py, and smoke_test.py so there is one place to
update after a redeploy instead of three.
"""

PROJECT_ID = "klara-nonprod"
LOCATION = "us-central1"
RESOURCE_NAME = "projects/335505349498/locations/us-central1/reasoningEngines/5955858224837033984"

CONFIRMATION_FUNCTION_NAME = "adk_request_confirmation"
