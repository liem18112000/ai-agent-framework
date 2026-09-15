"""Evaluation configuration constants, grouped by type — one module per type:
`adk_metrics` (ADK criteria/thresholds), `partitions` (the EP/BVA matrix), `views` (golden views),
`layers` (PQS/TPS component -> 3-layer grouping). Import from the submodule or this facade."""

from __future__ import annotations

from test_evaluation.config.adk import (
    JUDGED_METRICS,
    JUDGED_THRESHOLD,
    NATIVE_TRAJECTORY_METRIC,
    TEST_CONFIG,
)
from test_evaluation.config.layers import PQS_LAYERS, TPS_LAYERS
from test_evaluation.config.partitions import FULL_MATRIX
from test_evaluation.config.views import GOLDEN_VIEWS

__all__ = [
    "FULL_MATRIX", "GOLDEN_VIEWS", "JUDGED_METRICS", "JUDGED_THRESHOLD",
    "NATIVE_TRAJECTORY_METRIC", "PQS_LAYERS", "TEST_CONFIG", "TPS_LAYERS",
]
