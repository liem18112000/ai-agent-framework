"""The evaluation engines — score a persisted KGA pack (PQS) or TPD plan+suite (TPS).

Facade over the SOLID-split modules: `loaders` (data access), `pack` (KGA → PQS), `plan` (TPD → TPS).
Import from here (`from test_evaluation.engine import evaluate_pack, evaluate_plan`)."""

from __future__ import annotations

from test_evaluation.engine.pack import evaluate_pack
from test_evaluation.engine.plan import evaluate_plan

__all__ = ["evaluate_pack", "evaluate_plan"]
