"""Jira / Confluence attachment fetcher — download the file with the AUTHENTICATED Atlassian client
(the web fetcher can't: no auth + it rejects non-HTML) and extract its text (PDF / .docx / .xlsx /
CSV / text / image-OCR). This is why the spec PDFs attached to a ticket now reach the pack instead of
being recorded-only 'gaps'."""

from __future__ import annotations

import asyncio

from common.extract.attachment import attachment_text
from common.models import ATTACHMENT, LinkRecord, Note, Scope
from knowledge_gathering.gather.crawl.fetch.base import NodeFetcher


class AttachmentFetcher(NodeFetcher):
    """``attachment:<download-url>`` — authed download + text extraction into a leaf Note."""

    kind = "attachment"

    async def fetch(self, client, ident: str, nid: str, scope: Scope) -> tuple[list[LinkRecord], Note, str]:
        # ident is the absolute, authenticated download URL (canonical = attachment:<url>).
        data, ctype, filename = await client.download_bytes(ident)
        title = filename or ident.rstrip("/").rsplit("/", 1)[-1] or "attachment"
        # extraction is blocking (pypdf / openpyxl / Vertex vision) → run off the event loop
        text = await asyncio.to_thread(attachment_text, data, ctype, filename or title)
        return [], Note(id=nid, type=ATTACHMENT, title=title, source_url=ident, links=[]), text
