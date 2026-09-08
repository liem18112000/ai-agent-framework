"""RoundQuestions — one heuristic-question strategy per interrogation round."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import ClassVar

from common.interrogate.pack import Pack
from common.models import Note, Question

QFactory = Callable[..., Question]


class RoundQuestions(ABC):
    """Strategy that derives the heuristic questions for ONE interrogation round."""

    round: ClassVar[str] = ""
    registry: ClassVar[dict[str, RoundQuestions]] = {}

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if cls.round:
            RoundQuestions.registry[cls.round] = cls()

    @abstractmethod
    def build(self, pack: Pack, primary: Note | None, title: str, q: QFactory) -> list[Question]:
        """Return this round's questions; `q(**kw)` stamps id/round and builds a Question."""
        raise NotImplementedError
