# devops-3f9a ops-docs RAG corpus

devops-3f9a has a `search_ops_docs` tool backed by a Vertex AI RAG Engine
corpus indexing documentation across the LUZ ops repo, so the agent can
answer questions about naming conventions, setup steps, and known gaps
instead of guessing.

## Corpus

```
projects/335505349498/locations/europe-west6/ragCorpora/5148740273991319552
```

Referenced as `_RAG_CORPUS` in `devops_3f9a/agent.py`. Display name
`devops-3f9a-corpus`. Production config:

- **Scaled tier** managed-DB backend (not `Basic`, the default/dev
  tier) -- set at the region level via
  `rag.update_rag_engine_config(..., rag_managed_db_config=RagManagedDbConfig(tier=Scaled()))`
  for `europe-west6` before creating the corpus. Tier is a
  region/project-wide setting, not a per-corpus one -- every corpus
  created in `europe-west6` for this project now provisions on the
  Scaled tier.
- Embedding model pinned explicitly to `text-embedding-005` via
  `backend_config=RagVectorDbConfig(rag_embedding_model_config=...)` on
  `create_corpus` (this was already the default, pinning it just makes
  it explicit and stable against future default changes).
- Ingested with an **LLM parser** (`llm_parser=LlmParserConfig(model_name=".../gemini-2.5-flash")`
  on `import_files`) instead of naive text-chunking -- a Gemini call
  parses each document before chunking/embedding, which handles
  markdown tables and structure (e.g. the CIDR and cluster-inventory
  tables in the indexed docs) far better than a plain text splitter.
  Slower to import (one LLM call per doc) but a real quality
  improvement for docs with tabular/structured content.
- `VertexAiRagRetrieval` in `agent.py` sets explicit
  `similarity_top_k=5` and `vector_distance_threshold=0.5` rather than
  leaving retrieval tuning at SDK defaults.

**Superseded corpora, in order:** `us-west1` (workaround for a region
restriction, migrated away) -> `europe-west6` display name
`devops-3f9a-ops-docs` (Basic tier, plain chunking, `ragCorpora/2227030015734710272`,
deleted) -> a first `devops-3f9a-corpus` attempt on Scaled tier
(`ragCorpora/7454583283205013504`) whose import got permanently stuck,
deleted and recreated -> the current corpus above.

**Why `europe-west6` (Zurich):** LUZ's own workloads (the `klara-nonprod`
GKE cluster itself, etc.) run in `europe-west6`, and EU/Swiss data
residency is the actual requirement here -- so the corpus belongs there,
not in the US.

`europe-west6` was not the first region tried. This agent's Agent Engine
deployment and staging bucket are `us-central1`, and RAG Engine's default
Spanner-backed mode (`Basic`/`Scaled` tier) is capacity-restricted to
allowlisted projects in `us-central1`/`us-east1`/`us-east4` for new
projects -- so the corpus was first created in `us-west1` to route
around that. That was a mistake: the restriction is specific to those
three regions, not a general regional limitation, and `europe-west6`
works directly with no workaround needed. The corpus was migrated
(re-created + re-imported) from `us-west1` to `europe-west6`; the old
`us-west1` corpus was deleted.

**Residency caveat -- this only fixes the corpus and the storage layer,
not the whole agent.** The GCS staging bucket is now `europe-west6` too
(see "Storage bucket" below), but the Agent Engine deployment itself
(the reasoning engine resource,
`projects/335505349498/locations/us-central1/reasoningEngines/...`) --
the actual compute that runs this agent's model calls and tool code --
is still `us-central1`.

Cross-region reference from the agent (`us-central1`) to both the corpus
and the staging bucket (`europe-west6`) works fine within the same
project -- confirmed by redeploying after the bucket migration. But if
EU/Swiss residency needs to hold for this agent end-to-end, moving the
deployment region itself is a separate, larger change (would need a new
Agent Engine resource, since reasoning engines aren't region-migratable
in place).

## Storage bucket

Both the RAG source docs and this agent's Agent Engine build artifacts
live in one shared bucket:

```
gs://luz-agentic-storage-3808ce15-44f3-447c-a037-5d5ff87df2e0
```

- `europe-west6`, `STANDARD` storage class (`RAPID` -- GCS's newer
  zonal, lower-latency class -- isn't offered in `europe-west6` for
  this project; tested directly, rejected for both a zonal
  `europe-west6-a` location and a plain regional one. `STANDARD` is the
  fastest class actually available there).
- Uniform bucket-level access, public access prevention enforced (never
  reachable from the public internet).
- Soft-delete enabled, 90-day retention.
- Layout:
  - `agent_engine/` -- Agent Engine build artifacts (`agent_engine.pkl`,
    `requirements.txt`, `dependencies.tar.gz`), written automatically by
    the SDK. **`deployment/deploy.py`'s `STAGING_BUCKET` must be the
    bare bucket root** (`gs://luz-agentic-storage-...`), not
    `gs://luz-agentic-storage-.../agent_engine` -- the `agent_engines`
    SDK parses `staging_bucket` as a literal bucket *name* and tries to
    `create_bucket()` it if given a path with a slash in it, which fails
    with `Invalid bucket name`. The SDK adds the `agent_engine/` prefix
    inside the bucket itself.
  - `agent_knowledge/<agent-name>/` -- per-agent knowledge/RAG source
    docs, one subfolder per agent that uses this bucket. This agent's
    docs are under `agent_knowledge/devops-3f9a/rag-docs/`.

This bucket replaced the old per-purpose
`klara-nonprod-agent-engine-staging-us-central1` bucket (`us-central1`,
default settings) for devops-3f9a. That old bucket was left alone, not
deleted -- `sba-us-central1` (the other reference agent in this repo)
may still use it.

## What's indexed

~67 markdown files, curated (not the whole repo) via a staging copy at
publish time -- there's no ongoing sync:

- `agent/devops/*.md` (this agent's own README/DEPLOY docs)
- `.claude/agents/gcp-*.md` and `.claude/skills/gcp-*/SKILL.md` (the GCP
  domain runbooks: GKE, IAM, network, secrets, observability, pubsub,
  GCS, Cloud Run)
- `*.md`/`readme.md` across `luz_kubernetes/`, `luz_kubernetes_infra/`,
  and `luz_dockerfiles/` (terraform modules, kustomize overlays, runtime
  agent instructions, Docker image build docs)

Excluded: vendored third-party library docs (e.g. the Keycloak theme's
bundled Angular treeview README) -- noise, not ops knowledge.

## Refreshing the corpus

There's no automation for this yet -- docs drift out of date until
someone re-runs the import. To refresh:

```powershell
# 1. Re-stage the curated doc set (same file list as above) to a local dir,
#    then upload it, replacing what's there:
gcloud storage rsync -r <local-staging-dir> `
  gs://luz-agentic-storage-3808ce15-44f3-447c-a037-5d5ff87df2e0/agent_knowledge/devops-3f9a/rag-docs

# 2. Re-import with the LLM parser (skips files already indexed; delete
#    + re-add a RagFile via rag.delete_file if you need to force a
#    specific file to refresh):
python -c "
import vertexai
from vertexai import rag
vertexai.init(project='klara-nonprod', location='europe-west6')
rag.import_files(
    'projects/335505349498/locations/europe-west6/ragCorpora/5148740273991319552',
    paths=['gs://luz-agentic-storage-3808ce15-44f3-447c-a037-5d5ff87df2e0/agent_knowledge/devops-3f9a/rag-docs'],
    llm_parser=rag.LlmParserConfig(
        model_name='projects/klara-nonprod/locations/europe-west6/publishers/google/models/gemini-2.5-flash',
    ),
)
"
```

`rag.import_files` on the whole GCS prefix occasionally returns a bare
`500 An internal error occurred` on the first attempt -- this was
transient when the corpus was first built (0 of 68 files landed, no
partial state to clean up) and succeeded on a plain retry. If it
persists across retries, fall back to importing files individually or
in small batches instead of the whole prefix at once.

It can also raise a client-side `TimeoutError` / `RetryError` (default
600s) while polling the long-running import operation, even though the
import completes server-side -- this happened importing 68 files into
`europe-west6`. Don't treat that as a failure by itself: check
`len(list(rag.list_files(corpus_name)))` before retrying or falling back
to per-file import, since a retry against files that already imported
just wastes time re-embedding them.

**A stuck import can permanently wedge a corpus.** While building the
current corpus, a plain-chunking `import_files` call left an
`ImportRagFilesOperationMetadata` LRO stuck at `done: False` indefinitely
(polled directly via
`aiplatform_v1.VertexRagDataServiceClient(...).transport.operations_client.get_operation(op_name)`
-- confirmed via both the API and the Cloud Console corpus page, which
showed the corpus as "Ready" with 0 files and *no* visible in-progress
import at all). This happened even after deleting all the files that
import had created (`rag.delete_file` on everything in
`rag.list_files`) -- the underlying import operation itself doesn't
clear, and the corpus refuses any new `import_files` call with `400
FailedPrecondition: There are other operations running on the
RagCorpus` for as long as that stale operation exists. Waited 60+
minutes with zero change. There's no documented way to cancel or clear
a stuck import operation directly.

The only fix found: **delete the whole corpus and recreate it** (`rag.delete_corpus`
then `rag.create_corpus` with the same config) -- cheap since a corpus
with 0 files has nothing to lose, but means the corpus's resource name
changes, so anything referencing the old ID (`agent.py`'s `_RAG_CORPUS`)
needs updating. If a future import ever gets stuck again with real data
already in the corpus, deleting files individually first (they're
independent of the stuck operation) before deleting/recreating the
corpus preserves nothing extra -- there's no known partial-recovery path,
so treat "stuck operation" as corpus-destroying and plan the refresh
accordingly.

## Vertex AI RAG Engine config note

`vertexai.rag` is itself a deprecated module (the SDK warns to migrate to
the `agentplatform` client eventually), but it's what `google-adk`'s
`VertexAiRagRetrieval` tool integrates with today, and it's what was used
here.

The RAG Engine config for `klara-nonprod`'s `us-central1` was changed
from the default `Basic` (Spanner-backed) tier to `Unprovisioned` while
diagnosing the region-capacity error above, before switching to
`us-west1` for the actual corpus. That config change is harmless (it's
just project/region-level config, not a running resource) but if
`us-central1` RAG Engine is ever needed for this project, its tier will
need to be set back to `Basic`/`Scaled` first via
`rag.update_rag_engine_config`.
