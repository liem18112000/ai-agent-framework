"""Back-compat shim — the shared memory-index predicates now live in `common.memory.graph_index`
(so the retrieval facade and the explore tiers share one copy without a KG/executor dependency).

Existing imports (`from knowledge_gathering.explore.index import match_index_nodes`, …) and the
test monkeypatches on this module's names keep working. New code should import from
`common.memory.graph_index` (or go through `common.memory.retrieve`).
"""

from __future__ import annotations

from common.memory.graph_index import graph_grounded, match_index_nodes, rank_promotions

__all__ = ["graph_grounded", "match_index_nodes", "rank_promotions"]
