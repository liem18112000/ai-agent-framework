"""Plain-text URL fallback — the last-resort source so a raw URL is never missed."""

from __future__ import annotations

import re

URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")


def regex_links(text: str) -> list[tuple[str, str]]:
    return [(u, "") for u in URL_RE.findall(text or "")]
