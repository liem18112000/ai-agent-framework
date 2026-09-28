"""Component -> 3-layer grouping for the PQS / TPS report render (the 3-layer eval framework — see the
RESEARCH docs). Layer 3 (downstream) is scored out-of-band, so it appears as a note, not a component."""

from __future__ import annotations

PQS_LAYERS = {
    "Layer 1 (artifact)": ("faithfulness", "ctx_precision", "ctx_recall", "relevancy"),
    "Layer 2 (process)": ("trajectory",),
}

TPS_LAYERS = {
    "Layer 1 (artifact)": ("brief_groundedness", "coverage", "oracle_strength", "fault_detection"),
    "Layer 2 (process)": ("trajectory",),
}
