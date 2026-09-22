"""The refine agent — KGA's HITL interrogation (Option B), driven by the router via `wants_refine`."""

from knowledge_gathering.refine.agent import build_refine_agent, wants_refine

__all__ = ["build_refine_agent", "wants_refine"]
