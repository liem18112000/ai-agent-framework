"""The gather agent — crawl + explore + domain, assembled by `build_gather_agent` (D15).

Public surface of the gather sub-package. Internal modules import each other by submodule path
(`.agent`, `.domain`, `.explore.*`, `.crawl.*`) — never via this `__init__` — so there is no cycle."""

from knowledge_gathering.gather.agent import GatherAgent, build_gather_agent
from knowledge_gathering.gather.domain import (
    SeedProbe,
    parse_input,
    seed_probe,
    summarize_gather,
)

__all__ = [
    "GatherAgent",
    "SeedProbe",
    "build_gather_agent",
    "parse_input",
    "seed_probe",
    "summarize_gather",
]
