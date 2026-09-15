"""Attachment content extraction — turn a downloaded Jira/Confluence attachment into plain text for
the pack. Supports PDF, MS Word (.docx), MS Excel (.xlsx), CSV / text-like files, and images (OCR /
description via Claude-on-Vertex vision, degrading to a recorded placeholder when vision is not
configured, e.g. offline tests). Only these extractable types become ATTACHMENT links upstream
(extract/assemble.py filters on mime), so the fetcher never wastes a node on an unreadable blob.

Legacy binary Office formats (.doc / .xls, OLE) are NOT supported — they raise so the crawl records a
gap rather than fabricating text."""

from __future__ import annotations

import io

_TEXT_MIME_EXACT = frozenset({
    "application/json", "application/xml", "application/csv", "application/x-ndjson",
})
_TEXT_SUFFIXES = (".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".xml", ".log", ".yaml", ".yml")
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff")
# Anthropic vision accepts these media types directly; anything else we convert to PNG (Pillow).
_VISION_MIME = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # Anthropic per-image ceiling; larger → downscaled to PNG


def _kind(mime: str | None, filename: str | None) -> str:
    """Classify an attachment into an extractable family, or '' if we can't read it."""
    mime = (mime or "").split(";", 1)[0].strip().lower()
    fn = (filename or "").lower()
    if "pdf" in mime or fn.endswith(".pdf"):
        return "pdf"
    if mime == _DOCX_MIME or fn.endswith(".docx"):
        return "docx"
    if mime == _XLSX_MIME or fn.endswith((".xlsx", ".xlsm")):
        return "xlsx"
    if mime.startswith("image/") or fn.endswith(_IMAGE_SUFFIXES):
        return "image"
    if mime.startswith("text/") or mime in _TEXT_MIME_EXACT or fn.endswith(_TEXT_SUFFIXES):
        return "text"
    return ""


def is_extractable_attachment(mime: str | None, filename: str | None) -> bool:
    """True if we can turn this attachment into text — PDF, .docx, .xlsx, text/CSV, or an image
    (transcribed via vision). Non-extractable blobs (audio/video/archives/legacy Office) never become
    pack nodes."""
    return bool(_kind(mime, filename))


def attachment_text(data: bytes, mime: str | None, filename: str | None = "") -> str:
    """Extract plain text from `data`. Raises ValueError on a genuinely unsupported type (→ the crawl
    flags a gap, never fabricates content). Blocking (pypdf/openpyxl/Vertex) — call in a worker thread."""
    kind = _kind(mime, filename)
    if kind == "pdf":
        from pypdf import PdfReader  # lazy — keeps the base import light + offline tests fast

        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    if kind == "docx":
        return _docx_text(data)
    if kind == "xlsx":
        return _xlsx_text(data)
    if kind == "image":
        return _image_text(data, mime, filename)
    if kind == "text":
        return data.decode("utf-8", errors="replace").strip()
    raise ValueError(f"unsupported attachment type mime={mime!r} filename={filename!r}")


def _docx_text(data: bytes) -> str:
    """Paragraphs + table cells of a .docx, in document order."""
    from docx import Document

    doc = Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts).strip()


def _xlsx_text(data: bytes) -> str:
    """Non-empty rows of every sheet, tab-joined, prefixed by sheet name."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out: list[str] = []
    for ws in wb.worksheets:
        out.append(f"# Sheet: {ws.title}")
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None and str(c).strip()]
            if cells:
                out.append("\t".join(cells))
    wb.close()
    return "\n".join(out).strip()


def _image_text(data: bytes, mime: str | None, filename: str | None) -> str:
    """Transcribe/describe an image via Claude-on-Vertex vision. Degrades to a recorded placeholder
    (never raises) when Vertex is unconfigured or the call fails — so the image is still a pack node."""
    from common.llm.vertex import describe_image, vertex_config

    label = filename or mime or "image"
    cfg = vertex_config()
    if not cfg:
        return f"[image attachment: {label} — vision transcription unavailable (Vertex not configured)]"
    project, location, model = cfg
    media_type, payload = _vision_payload(data, mime)
    try:
        text = describe_image(payload, media_type=media_type, project=project, location=location,
                              model=model, max_tokens=1500)
    except Exception as exc:  # noqa: BLE001 — vision is best-effort; record the image, don't fail the crawl
        return f"[image attachment: {label} — transcription failed: {exc}]"
    return text.strip() or f"[image attachment: {label} — no text detected]"


def _vision_payload(data: bytes, mime: str | None) -> tuple[str, bytes]:
    """Return (media_type, bytes) accepted by Anthropic vision — pass PNG/JPEG/GIF/WebP through;
    convert anything else (BMP/TIFF/…), or an oversized image, to a bounded PNG via Pillow."""
    mt = (mime or "").split(";", 1)[0].strip().lower()
    if mt in _VISION_MIME and len(data) <= _MAX_IMAGE_BYTES:
        return mt, data
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((2000, 2000))  # bound dimensions → keeps the PNG under the per-image ceiling
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return "image/png", buf.getvalue()
