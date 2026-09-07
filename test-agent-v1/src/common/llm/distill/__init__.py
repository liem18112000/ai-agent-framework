"""Distill a node into a synopsis — heuristic by default, Claude on Vertex when configured."""

from common.llm.distill.claude import claude_distill
from common.llm.distill.factory import make_distiller
from common.llm.distill.heuristic import heuristic_distill

__all__ = ["claude_distill", "heuristic_distill", "make_distiller"]
