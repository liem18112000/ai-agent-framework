"""Interrogation round strategies — one module-level `build_*` per round + the `REGISTRY` lookup.

Each `build_*(pack, primary, title, q)` returns that round's heuristic questions; `q(**kw)` stamps
id/round and builds a Question. `REGISTRY` maps round name -> builder (dispatched by
`common.interrogate.questions.build_round_questions`). No ABC, no import-time self-registration.
"""

from __future__ import annotations

from collections.abc import Callable

from common.interrogate.round.business import build_business
from common.interrogate.round.case_design import build_case_design
from common.interrogate.round.data_design import build_data_design
from common.interrogate.round.methodology import build_methodology
from common.interrogate.round.metrics import build_metrics
from common.interrogate.round.qa import build_qa
from common.interrogate.round.scope import build_scope
from common.interrogate.round.step_oracle import build_step_oracle
from common.interrogate.round.technical import build_technical
from common.interrogate.round.test_design import build_test_design
from common.models import Question

QFactory = Callable[..., Question]

REGISTRY: dict[str, Callable[..., list[Question]]] = {
    "business": build_business,
    "technical": build_technical,
    "qa": build_qa,
    "scope": build_scope,
    "methodology": build_methodology,
    "metrics": build_metrics,
    "test-design": build_test_design,
    "case-design": build_case_design,
    "data-design": build_data_design,
    "step-oracle": build_step_oracle,
}

__all__ = ["REGISTRY", "QFactory"]
