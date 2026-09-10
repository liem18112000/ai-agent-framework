"""Interrogation round strategies — one module per round, auto-registered into the registry."""

from common.interrogate.round import (  # noqa: F401  (import side effect: registration)
    business,
    case_design,
    data_design,
    methodology,
    metrics,
    qa,
    scope,
    step_oracle,
    technical,
    test_design,
)
from common.interrogate.round.base import QFactory, RoundQuestions

__all__ = ["QFactory", "RoundQuestions"]
