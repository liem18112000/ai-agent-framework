"""Shared executor utilities.

These are package-agnostic A2A helpers, so they are reused verbatim from
knowledge_gathering rather than duplicated. `build_bank` gives both agents the same
GCS memory bank (same GCS_BUCKET). Re-exported here as this package's stable import seam —
if test_plan_definition later needs its own variant, only this module changes.
"""

from common.executor import build_bank, now, reply

__all__ = ["build_bank", "now", "reply"]
