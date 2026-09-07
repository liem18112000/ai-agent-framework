"""Confluence storage-format (XHTML) link extraction."""

from __future__ import annotations

from bs4 import BeautifulSoup

from common.extract.regex_urls import URL_RE


def storage_links(html: str) -> list[tuple[str, str]]:
    """(url, anchor) from <a href>, plus any URL in the XML (ri:url macros, raw)."""
    soup = BeautifulSoup(html or "", "html.parser")
    out = [(a["href"], a.get_text(strip=True)) for a in soup.find_all("a", href=True)]
    out += [(u, "") for u in URL_RE.findall(html or "")]
    return out
