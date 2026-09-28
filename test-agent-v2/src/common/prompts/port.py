"""The prompt-store port (P0) — storage-agnostic. Imports neither ADK nor the DB.

Why ``$``-substitution and not ``str.format``: our prompt bodies are full of LITERAL braces — the
JSON shapes we demand back (``{"items": [ ... ]}``), the per-item field lists, the ``{var}`` examples.
``format``/``format_map`` would treat every one of those as a placeholder and raise (or silently eat
them). ``string.Template`` uses ``$name``, which appears nowhere in our prompts, so the literal braces
survive untouched — the same reason the ADK instruction is a closure today rather than a raw string
(see ``common/testplan/llm/adk.build_generator_agent``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from string import Template
from typing import Protocol

#: The only rendering mode: ``$name`` substitution here, literal braces preserved. Kept as a stored
#: column so a future mode is additive, but every template uses this one — do not add a second until
#: something actually needs it.
NONE = "none"

_VAR = re.compile(r"\$(\w+)|\$\{(\w+)\}")


class PromptNotFound(KeyError):
    """No template is published under this key (and no Python default backs it)."""


def declared_vars(body: str) -> tuple[str, ...]:
    """Every ``$name`` / ``${name}`` placeholder in ``body``, in first-seen order."""
    seen: dict[str, None] = {}
    for m in _VAR.finditer(body):
        seen.setdefault(m.group(1) or m.group(2), None)
    return tuple(seen)


@dataclass(frozen=True)
class PromptTemplate:
    """One immutable, addressable prompt body."""

    key: str
    body: str
    version: int = 0          # 0 = the Python default; DB-published versions start at 1
    engine: str = NONE
    required_vars: tuple[str, ...] = ()
    #: Substrings ANY body published under this key must contain — the output contract the consuming
    #: parser depends on. Travels with the key's definition so `publish()` can enforce it without the
    #: store importing a domain module.
    contract: tuple[str, ...] = ()
    #: Substrings a published body must NOT contain. Needed because the contract is per key and
    #: sometimes inverted: the testplan generators must never say "Return ONLY a JSON array", while
    #: `engine.questions` MUST (it is parsed by `loads_array`).
    forbids: tuple[str, ...] = ()
    #: True when this row was written by `prompt_seed` and never hand-edited since. Such a row is a
    #: COPY of an image body, not an intentional override, so it must not outrank a newer image.
    seeded: bool = False

    def render(self, params: Mapping[str, object] | None = None) -> str:
        """Substitute ``$name`` params into the body (``engine="none"`` only).

        Missing params are a hard error rather than a silently half-rendered prompt — a prompt with an
        unsubstituted ``$scope_block`` in it reads as instructions to the model and is worse than a
        crash. Unknown EXTRA params are ignored, so a caller may pass a superset."""
        p = dict(params or {})
        missing = [v for v in self.required_vars if v not in p]
        if missing:
            raise ValueError(f"prompt {self.key!r} missing params: {', '.join(missing)}")
        return Template(self.body).safe_substitute(p)


class PromptStore(Protocol):
    """Where prompt bodies come from.

    ``get`` is SYNC on purpose: prompts are rendered from both async agent paths and sync engine paths
    (``define``'s question/brief builders call the blocking ``complete()``), and the Cloud SQL engine is
    async — so a store that hit the DB per call could not serve both. Instead the store serves a
    process-local SNAPSHOT, and ``refresh`` (async, called once at run start) is the only thing that
    touches the backing source. That also gives P4 version pinning for free: every ``get`` inside one
    run reads the same snapshot, so a mid-run publish cannot make round 3 incomparable to round 1."""

    def get(self, key: str) -> PromptTemplate: ...

    async def refresh(self) -> None: ...

    def pinned(self) -> dict[str, int]: ...
