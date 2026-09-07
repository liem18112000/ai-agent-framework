"""Seed normalization → canonical node id (jira:KEY / confluence:ID)."""

from __future__ import annotations

import re

from common.extract import classify_url


def normalize_seed(seed: str) -> str:
    if re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", seed):
        return f"jira:{seed}"
    if seed.isdigit():
        return f"confluence:{seed}"
    if seed.startswith("http"):
        return classify_url(seed)[1]
    if re.fullmatch(r"[\w.-]+/[\w.-]+", seed):  # "<ws>/<repo>" → build its code graph
        return f"codegraph:{seed}"
    return seed
