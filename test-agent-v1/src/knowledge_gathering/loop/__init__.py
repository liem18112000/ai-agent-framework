"""Knowledge Gathering loop — bounded, concurrent frontier crawl."""

from knowledge_gathering.loop.crawl import crawl
from knowledge_gathering.loop.fetch import fetch_node
from knowledge_gathering.loop.seed import normalize_seed
from knowledge_gathering.models import CrawlResult

__all__ = ["CrawlResult", "crawl", "fetch_node", "normalize_seed"]
