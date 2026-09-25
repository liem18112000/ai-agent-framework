"""DDL for the pgvector recall tier (M0). `memory_node` carries the embedding + tsvector +"""

from __future__ import annotations

from common.env import env_int

EMBED_DIMS = env_int("MEMORY_EMBED_DIMS", 768)

SCHEMA_SQL = f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS memory_node (
  id           text PRIMARY KEY,
  type         text NOT NULL,
  kind         text,
  title        text,
  synopsis     text,
  source_url   text,
  content_uri  text,
  run_id       text,
  context_id   text,
  scope        text NOT NULL DEFAULT 'context',
  status       text NOT NULL DEFAULT 'active',
  confidence   text NOT NULL DEFAULT 'high',
  created_at   timestamptz NOT NULL DEFAULT now(),
  embedding    vector({EMBED_DIMS}),
  tsv          tsvector GENERATED ALWAYS AS (
                 to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(synopsis,''))
               ) STORED,
  meta         jsonb NOT NULL DEFAULT '{{}}'
);

CREATE INDEX IF NOT EXISTS memory_node_tsv_gin    ON memory_node USING gin (tsv);
CREATE INDEX IF NOT EXISTS memory_node_filter     ON memory_node (type, scope, status);
CREATE INDEX IF NOT EXISTS memory_node_run        ON memory_node (run_id);

CREATE TABLE IF NOT EXISTS memory_edge (
  source_id  text NOT NULL,
  target     text NOT NULL,
  type       text,
  origin     text,
  in_scope   boolean DEFAULT false,
  PRIMARY KEY (source_id, target)
);
CREATE INDEX IF NOT EXISTS memory_edge_target ON memory_edge (target);
"""

HNSW_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS memory_node_embedding_hnsw "
    "ON memory_node USING hnsw (embedding vector_cosine_ops);"
)
