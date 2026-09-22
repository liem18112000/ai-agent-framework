"""Interrogation round strategies — one module per round, auto-registered into the registry.

Importing this package registers every round (KGA refine: business/technical/qa; TPD define:
methodology/scope/metrics) with RoundQuestions.registry, so build_round_questions can dispatch by
name. Add a round = add a module here and list it below (Open/Closed).
"""

# Import each round so its subclass self-registers via __init_subclass__.
from common.interrogate.round import (  # noqa: F401  (import side effect: registration)
    business,
    methodology,
    metrics,
    qa,
    scope,
    technical,
)
from common.interrogate.round.base import QFactory, RoundQuestions

__all__ = ["QFactory", "RoundQuestions"]
