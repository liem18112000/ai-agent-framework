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

"""Shared, hard-coded safety configuration for the devops-3f9a GKE agent.

This is enforced in code (every tool checks against ALLOWED_PROJECTS),
not just in the prompt instructions -- the model refusing to ask for a
disallowed project is not a safety boundary, this file is.
"""

ALLOWED_PROJECTS = frozenset(
    {
        "klara-nonprod",
        "klara-performance",
        "klara-infra",
        "klara-repo",
    }
)

EXCLUDED_PROJECTS = frozenset({"klara-prod"})


class DisallowedProjectError(Exception):
    """Raised when a tool is asked to act on a project outside ALLOWED_PROJECTS."""


def assert_project_allowed(project_id: str) -> None:
    if project_id not in ALLOWED_PROJECTS:
        raise DisallowedProjectError(
            f"Project '{project_id}' is not in the allowed scope for this agent "
            f"({sorted(ALLOWED_PROJECTS)}). klara-prod is permanently excluded "
            "and this agent will never act on it, regardless of what is asked."
        )
