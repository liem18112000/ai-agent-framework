"""URL classification → (type, canonical dedup key)."""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

from common.models import (
    ATTACHMENT,
    BITBUCKET,
    CODEGRAPH,
    CONFLUENCE_PAGE,
    EXTERNAL_WEB,
    FIGMA,
    GITHUB,
    GOOGLE_DOC,
    JIRA_ISSUE,
)


def _github_host() -> str:
    """Enterprise Server browser host from GITHUB_API_BASE (`https://<host>/api/v3` → `<host>`); '' if unset."""
    return urlparse(os.environ.get("GITHUB_API_BASE", "")).netloc.lower()


def classify_url(url: str) -> tuple[str, str]:
    """Return (type, canonical_url). Canonical is a stable dedup key."""
    p = urlparse(url)
    host, path = p.netloc.lower(), p.path
    if "atlassian.net" in host and "/wiki/" in path:
        return CONFLUENCE_PAGE, (f"confluence:{m.group(1)}" if (m := re.search(r"/pages/(\d+)", path)) else url)
    if "atlassian.net" in host and "/browse/" in path:
        return JIRA_ISSUE, f"jira:{path.split('/browse/')[1].split('/')[0]}"
    if "/rest/api/3/attachment/" in path or "/wiki/download/" in path or "/download/attachments/" in path:
        return ATTACHMENT, f"attachment:{url}"  # route to the authed AttachmentFetcher, not the web fetcher
    if "bitbucket.org" in host:
        if m := re.match(r"/([^/]+)/([^/]+)/src/([^/]+)/(.+)$", path):
            return BITBUCKET, f"bitbucket:{m.group(1)}/{m.group(2)}/src/{m.group(3)}/{m.group(4)}"
        if r := re.fullmatch(r"/([^/]+)/([^/]+)/?", path):
            return CODEGRAPH, f"codegraph:{r.group(1)}/{r.group(2)}"
        return BITBUCKET, url
    if host == "raw.githubusercontent.com":  # raw file: /<owner>/<repo>/<ref>/<path> → same github: node
        if m := re.match(r"/([^/]+)/([^/]+)/([^/]+)/(.+)$", path):
            return GITHUB, f"github:{m.group(1)}/{m.group(2)}/blob/{m.group(3)}/{m.group(4)}"
        return GITHUB, url
    if host == "github.com" or host == _github_host():
        # a file (blob) URL → a fetchable github: node; anything else (repo root, PR, …) recorded-only
        if m := re.match(r"/([^/]+)/([^/]+)/blob/([^/]+)/(.+)$", path):
            return GITHUB, f"github:{m.group(1)}/{m.group(2)}/blob/{m.group(3)}/{m.group(4)}"
        return GITHUB, url
    if "figma.com" in host:
        return FIGMA, url
    if host in ("docs.google.com", "drive.google.com"):
        return GOOGLE_DOC, url
    return EXTERNAL_WEB, url
