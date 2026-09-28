"""Atlassian Document Format (ADF) extraction — link marks, smart-cards, plain text."""

from __future__ import annotations


def adf_links(node) -> list[tuple[str, str]]:
    """(url, anchor) from ADF link marks and inline/block/embed smart-cards."""
    out: list[tuple[str, str]] = []
    _walk_adf(node, out)
    return out


def _walk_adf(node, out: list[tuple[str, str]]) -> None:
    if isinstance(node, dict):
        if node.get("type") == "text":
            for mark in node.get("marks", []):
                if mark.get("type") == "link" and (href := mark.get("attrs", {}).get("href")):
                    out.append((href, node.get("text", "")))
        elif node.get("type") in ("inlineCard", "blockCard", "embedCard") and (url := node.get("attrs", {}).get("url")):
            out.append((url, ""))
        for child in node.get("content", []) or []:
            _walk_adf(child, out)
    elif isinstance(node, list):
        for child in node:
            _walk_adf(child, out)


def adf_text(node) -> str:
    """Concatenate all text in an ADF tree (for the regex fallback)."""
    parts: list[str] = []
    _collect_text(node, parts)
    return " ".join(parts)


def _collect_text(node, parts: list[str]) -> None:
    if isinstance(node, dict):
        if node.get("type") == "text" and node.get("text"):
            parts.append(node["text"])
        for child in node.get("content", []) or []:
            _collect_text(child, parts)
    elif isinstance(node, list):
        for child in node:
            _collect_text(child, parts)
