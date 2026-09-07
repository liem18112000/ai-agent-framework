"""NodeFetcher — one fetcher strategy per node kind (jira / confluence / bitbucket / …).

Polymorphism over the old `if kind == ...` chain: each fetcher handles one source, and a new
subclass self-registers via __init_subclass__ with NO change to fetch_node (Open/Closed). Every
fetcher honours the same `fetch(...) -> (links, note, text)` contract. A node id is
`"<kind>:<ident>"` (e.g. "jira:LUZ-158390"); the prefix selects the fetcher.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from common.models import LinkRecord, Note, Scope


class NodeFetcher(ABC):
    """Fetch + extract one node of a given ``kind`` into ``(links, note, body_text)``."""

    #: node-id prefix this fetcher handles; subclasses MUST set it.
    kind: ClassVar[str] = ""

    #: kind -> fetcher instance, populated automatically as subclasses are defined.
    registry: ClassVar[dict[str, NodeFetcher]] = {}

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if cls.kind:
            NodeFetcher.registry[cls.kind] = cls()

    @abstractmethod
    async def fetch(
        self, client, ident: str, nid: str, scope: Scope
    ) -> tuple[list[LinkRecord], Note, str]:
        """Fetch node ``nid`` (``ident`` is the part after the ``kind:`` prefix).

        Returns the outbound links found, the distilled Note stub, and the raw body text.
        """
        raise NotImplementedError
