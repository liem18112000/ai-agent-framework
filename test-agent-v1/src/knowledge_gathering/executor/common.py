"""KG executor seam — generic helpers reused from common, plus the KG-specific client.

`now`, `reply`, `build_bank` are generic (see common.executor); `build_client` builds the
read-only Atlassian client from env (+ optional Bitbucket auth) and stays here.
"""

from __future__ import annotations

import os

from common.atlassian import AtlassianClient
from common.executor import build_bank, now, reply

__all__ = ["build_bank", "build_client", "now", "reply"]


def build_client() -> AtlassianClient:
    bb_user = os.environ.get("ATLASSIAN_BITBUCKET_USERNAME")
    bb_pass = os.environ.get("ATLASSIAN_BITBUCKET_APP_PASSWORD")
    return AtlassianClient(
        os.environ["ATLASSIAN_BASE_URL"],
        os.environ["ATLASSIAN_EMAIL"],
        os.environ["ATLASSIAN_API_TOKEN"],
        bitbucket_auth=(bb_user, bb_pass) if bb_user and bb_pass else None,
    )
