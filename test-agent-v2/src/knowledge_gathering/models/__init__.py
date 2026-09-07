"""Data contracts for the Knowledge-Gathering agent (stdlib dataclasses).

The agent's own records live here; the generic, shared contracts stay in `common.models`.
Currently just the crawl-loop result, re-exported flat for `from knowledge_gathering.models import <name>`.
"""

from knowledge_gathering.models.crawl import CrawlResult

__all__ = ["CrawlResult"]
