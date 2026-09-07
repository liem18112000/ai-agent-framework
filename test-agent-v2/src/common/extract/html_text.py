"""Stdlib HTML → readable text (roadmap G3 external-web fetcher).

Uses `html.parser` (no new dep — bs4 is reserved for Confluence storage XHTML in
storage_html.py) to strip tags, drop <script>/<style>/<noscript>/<template> content, pull the
<title>, and collapse whitespace. Deliberately small: the web fetcher only needs a readable
body to distill + cite, not a faithful DOM.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

_SKIP = {"script", "style", "noscript", "template"}
_BLOCK = {
    "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "header", "footer", "table", "ul", "ol", "blockquote", "pre",
}


class _Extractor(HTMLParser):
    """Collect body text (minus skipped tags) and the document <title>."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._title: list[str] = []
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in _SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        if tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        if tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._in_title:
            self._title.append(data)
            return
        self.parts.append(data)

    @property
    def title(self) -> str:
        return "".join(self._title).strip()


def _collapse(text: str) -> str:
    """Collapse intra-line whitespace; keep non-empty lines as paragraph breaks."""
    lines = (re.sub(r"[ \t\f\v\r]+", " ", ln).strip() for ln in text.splitlines())
    return "\n".join(ln for ln in lines if ln).strip()


def parse_html(html: str) -> tuple[str, str]:
    """Return (readable_text, title) for an HTML document."""
    p = _Extractor()
    p.feed(html or "")
    p.close()
    return _collapse("".join(p.parts)), p.title


def html_to_text(html: str) -> str:
    return parse_html(html)[0]


def html_title(html: str) -> str:
    return parse_html(html)[1]
