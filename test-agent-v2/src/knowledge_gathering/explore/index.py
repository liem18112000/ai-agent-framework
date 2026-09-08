"""Back-compat shim — the shared memory-index predicates now live in `common.memory.graph_index`"""

from __future__ import annotations

from common.memory.graph_index import graph_grounded, match_index_nodes, rank_promotions

__all__ = ["graph_grounded", "match_index_nodes", "rank_promotions"]
