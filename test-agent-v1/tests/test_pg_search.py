"""M4: RRF fusion (pure) + the facade embedding-wiring for hybrid search-memory."""

from __future__ import annotations

from common.memory import retrieve
from common.memory.pg import embed
from common.memory.pg.store import rrf_fuse
from common.models import Graph

# --- rrf_fuse (pure, the one offline-testable piece of the hybrid path) --- #

def test_rrf_orders_by_fused_score():
    # 'b' appears high in both lists → should top the fusion
    fused = rrf_fuse(["a", "b", "c"], ["b", "d"])
    assert fused[0] == "b"
    assert set(fused) == {"a", "b", "c", "d"}


def test_rrf_rank_one_beats_a_single_low_rank():
    # 'x' is rank 1 in one list; 'y' only appears once at rank 3 → x outranks y
    assert rrf_fuse(["x"], ["z", "w", "y"])[0] == "x"


def test_rrf_limit_and_tiebreak():
    fused = rrf_fuse(["a"], ["b"], limit=1)          # equal scores → id-asc tie-break, then cut to 1
    assert fused == ["a"]


# --- facade: query embedding is passed to the store when Vertex is configured --- #

class _RecordingStore:
    def __init__(self):
        self.seen_embed = "unset"
        self.rows = [{"id": "pg:1", "type": "jira-issue", "title": "Dunning run"}]

    async def search(self, *, q_text, q_embed=None):
        self.seen_embed = q_embed
        return self.rows


def _bank():
    class _B:
        def load_index(self):
            return Graph(), 0
    return _B()


async def test_search_embeds_query_when_vertex_configured(monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "postgres")
    monkeypatch.setattr(embed, "embed_configured", lambda: True)

    async def _fake_q(text):
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(embed, "aembed_query", _fake_q)
    store = _RecordingStore()
    rows = await retrieve.search_nodes(_bank(), "payment reminder", store=store)
    assert {r["id"] for r in rows} == {"pg:1"}
    assert store.seen_embed == [0.1, 0.2, 0.3]          # vector arm fed


async def test_search_lexical_only_when_vertex_unconfigured(monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "hybrid")
    monkeypatch.setattr(embed, "embed_configured", lambda: False)
    store = _RecordingStore()
    rows = await retrieve.search_nodes(_bank(), "payment reminder", store=store)
    assert {r["id"] for r in rows} == {"pg:1"}
    assert store.seen_embed is None                     # no embedding → lexical-only
