"""URL classification → (type, canonical dedup key)."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from common.models import (
    ATTACHMENT,
    BITBUCKET,
    CODEGRAPH,
    CONFLUENCE_PAGE,
    EXTERNAL_WEB,
    FIGMA,
    GOOGLE_DOC,
    JIRA_ISSUE,
)


def classify_url(url: str) -> tuple[str, str]:
    """Return (type, canonical_url). Canonical is a stable dedup key."""
    p = urlparse(url)
    host, path = p.netloc.lower(), p.path
    if "atlassian.net" in host and "/wiki/" in path:
        return CONFLUENCE_PAGE, (f"confluence:{m.group(1)}" if (m := re.search(r"/pages/(\d+)", path)) else url)
    if "atlassian.net" in host and "/browse/" in path:
        return JIRA_ISSUE, f"jira:{path.split('/browse/')[1].split('/')[0]}"
    if "/rest/api/3/attachment/" in path:
        return ATTACHMENT, url
    if "bitbucket.org" in host:
        if m := re.match(r"/([^/]+)/([^/]+)/src/([^/]+)/(.+)$", path):
            return BITBUCKET, f"bitbucket:{m.group(1)}/{m.group(2)}/src/{m.group(3)}/{m.group(4)}"
        if r := re.fullmatch(r"/([^/]+)/([^/]+)/?", path):
            return CODEGRAPH, f"codegraph:{r.group(1)}/{r.group(2)}"
        return BITBUCKET, url
    if "figma.com" in host:
        return FIGMA, url
    if host in ("docs.google.com", "drive.google.com"):
        return GOOGLE_DOC, url
    return EXTERNAL_WEB, url
