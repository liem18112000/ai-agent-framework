"""Knowledge Gathering loop — bounded, concurrent frontier crawl."""

from knowledge_gathering.gather.crawl.crawl import CrawlResult, crawl
from knowledge_gathering.gather.crawl.fetch import fetch_node

__all__ = ["CrawlResult", "crawl", "fetch_node"]
