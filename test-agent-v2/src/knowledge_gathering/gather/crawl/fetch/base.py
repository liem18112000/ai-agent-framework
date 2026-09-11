"""NodeFetcher — one fetcher strategy per node kind (jira / confluence / bitbucket / …)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from common.models import LinkRecord, Note, Scope


class NodeFetcher(ABC):
    """Fetch + extract one node of a given ``kind`` into ``(links, note, body_text)``."""

    kind: ClassVar[str] = ""

    registry: ClassVar[dict[str, NodeFetcher]] = {}

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if cls.kind:
            NodeFetcher.registry[cls.kind] = cls()

    @abstractmethod
    async def fetch(self, client, ident: str, nid: str, scope: Scope) -> tuple[list[LinkRecord], Note, str]:
        """Fetch node ``nid`` (``ident`` is the part after the ``kind:`` prefix)."""
