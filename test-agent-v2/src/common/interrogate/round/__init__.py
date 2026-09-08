"""Interrogation round strategies — one module per round, auto-registered into the registry."""

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
