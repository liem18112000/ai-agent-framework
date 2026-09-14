# devops-3f9a ops-docs RAG corpus

devops-3f9a has a `search_ops_docs` tool backed by a Vertex AI RAG Engine
corpus indexing documentation across the LUZ ops repo, so the agent can
answer questions about naming conventions, setup steps, and known gaps
instead of guessing.

## Corpus

```
projects/335505349498/locations/europe-west6/ragCorpora/2227030015734710272
```

Referenced as `_RAG_CORPUS` in `devops_3f9a/agent.py`.

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

**Residency caveat -- this only fixes the corpus, not the whole agent.**
Two other pieces of this agent are still `us-central1`:
- The GCS staging bucket (`klara-nonprod-agent-engine-staging-us-central1`)
  the source docs are uploaded to before `rag.import_files` reads them --
  transient build/staging data, not a long-term store, but it does
  physically transit `us-central1`.
- The Agent Engine deployment itself (the reasoning engine resource,
  `projects/335505349498/locations/us-central1/reasoningEngines/...`) --
  the actual compute that runs this agent's model calls and tool code.

Cross-region reference from the agent (`us-central1`) to the corpus
(`europe-west6`) works fine within the same project -- but if EU/Swiss
residency needs to hold for this agent end-to-end, not just the RAG
corpus, moving the deployment region and staging bucket is a separate,
larger change (would need a new Agent Engine resource, since reasoning
engines aren't region-migratable in place).

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
  gs://klara-nonprod-agent-engine-staging-us-central1/devops-3f9a-rag-docs

# 2. Re-import (skips files already indexed; delete + re-add a RagFile via
#    rag.delete_file if you need to force a specific file to refresh):
python -c "
import vertexai
from vertexai import rag
vertexai.init(project='klara-nonprod', location='europe-west6')
rag.import_files(
    'projects/335505349498/locations/europe-west6/ragCorpora/2227030015734710272',
    paths=['gs://klara-nonprod-agent-engine-staging-us-central1/devops-3f9a-rag-docs'],
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
