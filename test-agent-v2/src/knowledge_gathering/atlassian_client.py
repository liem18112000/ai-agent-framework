"""Read-only Atlassian client builder (framework-neutral; extracted from executor/common.py in C2)."""

from __future__ import annotations

import os

from common.atlassian import AtlassianClient


def build_client() -> AtlassianClient:
    bb_user = os.environ.get("ATLASSIAN_BITBUCKET_USERNAME")
    bb_pass = os.environ.get("ATLASSIAN_BITBUCKET_APP_PASSWORD")
    return AtlassianClient(
        os.environ["ATLASSIAN_BASE_URL"],
        os.environ["ATLASSIAN_EMAIL"],
        os.environ["ATLASSIAN_API_TOKEN"],
        bitbucket_auth=(bb_user, bb_pass) if bb_user and bb_pass else None,
    )
