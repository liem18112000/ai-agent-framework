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
        m = re.search(r"/pages/(\d+)", path)
        return CONFLUENCE_PAGE, (f"confluence:{m.group(1)}" if m else url)
    if "atlassian.net" in host and "/browse/" in path:
        key = path.split("/browse/")[1].split("/")[0]
        return JIRA_ISSUE, f"jira:{key}"
    if "/rest/api/3/attachment/" in path:
        return ATTACHMENT, url
    if "bitbucket.org" in host:
        m = re.match(r"/([^/]+)/([^/]+)/src/([^/]+)/(.+)$", path)  # a file at a ref
        if m:
            ws, repo, ref, fp = m.groups()
            return BITBUCKET, f"bitbucket:{ws}/{repo}/src/{ref}/{fp}"
        r = re.fullmatch(r"/([^/]+)/([^/]+)/?", path)  # a bare repo → build its code graph
        if r:
            return CODEGRAPH, f"codegraph:{r.group(1)}/{r.group(2)}"
        return BITBUCKET, url  # PR / commit / other — recorded, not fetchable
    if "figma.com" in host:
        return FIGMA, url
    if host in ("docs.google.com", "drive.google.com"):
        return GOOGLE_DOC, url
    return EXTERNAL_WEB, url
