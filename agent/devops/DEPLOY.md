# Deploying devops-3f9a from a local machine to Vertex AI Agent Engine

This walks through everything needed to take this agent from a local
checkout to a running Vertex AI Agent Engine deployment, the same way
`sba-us-central1` (the software-bug-assistant reference deployment) was
set up. Reuse this file as a template for any future `devops-{random}`
agent in this repo -- just swap the package/project names.

## 0. Prerequisites

- Python 3.12, and [`uv`](https://docs.astral.sh/uv/) for dependency management.
- `gcloud` CLI, authenticated (`gcloud auth login`) with a principal that
  has `roles/aiplatform.user` (or broader) on the target project.
  Application Default Credentials must also be set up:
  `gcloud auth application-default login`.
- The target GCP project (`klara-nonprod` here) must have
  `aiplatform.googleapis.com` enabled.

## 1. Create a venv and install pinned dependencies

**Pin exact versions, don't just take the floor from `pyproject.toml`.**
`google-adk`'s tool APIs move between minor versions (we hit a real break
going from `1.28.0` to `2.8.0` mid-session, and this repo pins to
`1.28.0` deliberately for that reason). Use the exact deps from
`pyproject.toml`:

```powershell
cd devops-3f9a
uv venv --python 3.12
uv pip install `
  "google-adk==1.28.0" `
  "mcp==1.26.0" `
  "google-cloud-aiplatform[agent-engines,evaluation]>=1.93.0" `
  "google-cloud-container>=2.55.0" `
  "kubernetes>=31.0.0" `
  "python-dotenv>=1.1.0"
```

## 2. One-time GCP setup

```powershell
# Staging bucket for Agent Engine build artifacts (skip if it already exists)
gcloud storage buckets create gs://klara-nonprod-agent-engine-staging-us-central1 `
  --project=klara-nonprod --location=us-central1 --uniform-bucket-level-access
```

**Custom runtime service account.** devops-3f9a deploys with a
dedicated runtime service account, `devops-agent-runtime-sa@klara-nonprod.iam.gserviceaccount.com`
(set as `SERVICE_ACCOUNT` in `deployment/deploy.py`, passed as
`service_account=` to `agent_engines.create`/`update`), instead of the
Agent Engine default per-project service agent. Two things need to
exist before deploying:

```bash
# Create the SA if it doesn't already exist.
gcloud iam service-accounts create devops-agent-runtime-sa \
  --project=klara-nonprod \
  --display-name="devops-3f9a Agent Engine runtime SA"

# The Reasoning Engine build/runtime service agent needs permission to
# attach (act as) this custom SA when creating/updating the engine.
gcloud iam service-accounts add-iam-policy-binding \
  devops-agent-runtime-sa@klara-nonprod.iam.gserviceaccount.com \
  --project=klara-nonprod \
  --member="serviceAccount:service-<PROJECT_NUMBER>@gcp-sa-aiplatform-re.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"
```

**GKE access for `devops-agent-runtime-sa`** -- required before any
tool call will actually work, not optional:

```bash
# Requires roles/resourcemanager.projectIamAdmin (or Owner) on each project.
# NOT yet granted for devops-3f9a as of its initial deployment -- do this
# deliberately, it's a real cross-project IAM change.
for proj in klara-nonprod klara-performance klara-infra klara-repo; do
  gcloud projects add-iam-policy-binding "$proj" \
    --member="serviceAccount:devops-agent-runtime-sa@klara-nonprod.iam.gserviceaccount.com" \
    --role="roles/container.admin"
done
```

Replace `<PROJECT_NUMBER>` with the *deploying* project's number (for
`klara-nonprod`, that's `335505349498` -- confirm with
`gcloud projects describe klara-nonprod --format='value(projectNumber)'`).
`devops-agent-runtime-sa` is per-agent (unlike the old default service
agent, which was shared per deploying-project) -- a second agent
deployed into `klara-nonprod` should get its own dedicated runtime SA
and its own grants, not reuse this one.

## 3. Verify the package imports cleanly, locally, before deploying

```powershell
$env:PYTHONPATH = (Get-Location)
.\.venv\Scripts\python.exe -c "from devops_3f9a.agent import root_agent; print(root_agent.name, [t.name for t in root_agent.tools])"
```

If this fails, fix it here -- a broken deploy takes minutes to fail
remotely and gives a much less obvious error (`cloudpickle` load
failures, missing-module errors) than a local import error does.

## 4. Deploy

**Run from the project root** (`devops-3f9a/`, not `deployment/`) --
`deploy.py`'s `extra_packages=["./devops_3f9a"]` is a relative path
resolved against the current working directory, and Agent Engine's
packaging preserves whatever path structure you give it. Passing an
absolute path here is a real trap: it tars the package in nested under
its full absolute path instead of at the tarball root, and the deployed
container fails at startup with `ModuleNotFoundError: No module named
'devops_3f9a'` -- hit exactly this while building this agent.

```powershell
$env:PYTHONPATH = (Get-Location)
.\.venv\Scripts\python.exe deployment\deploy.py
```

This prints `CREATED: projects/<num>/locations/us-central1/reasoningEngines/<id>`
on success. Save that resource name -- you'll need it for testing, for
updates, and for the MCP bridge config.

To **update** an existing deployment in place (code change, dependency
bump, anything short of scope requirements changing) instead of creating
a new one:

```powershell
.\.venv\Scripts\python.exe deployment\deploy.py --update "projects/<num>/locations/us-central1/reasoningEngines/<id>"
```

## 5. Smoke-test it

```python
import vertexai
from vertexai import agent_engines

vertexai.init(project="klara-nonprod", location="us-central1")
engine = agent_engines.get("projects/<num>/locations/us-central1/reasoningEngines/<id>")

for event in engine.stream_query(user_id="smoke-test", message="List clusters in klara-nonprod"):
    print(event)
```

If GKE IAM access (step 2) hasn't been granted yet, expect a permission
error here -- that confirms the deployment itself is healthy and only
the IAM grant is outstanding.

**Testing a mutating tool's confirmation flow specifically:** ask for
something like "restart the X deployment in namespace Y" -- the event
stream will include a function call named `adk_request_confirmation`
instead of running the action. To approve it, send a follow-up
`stream_query` call with:

```python
resume_message = {
    "role": "user",
    "parts": [{
        "function_response": {
            "id": "<the adk_request_confirmation call's id from the event>",
            "name": "adk_request_confirmation",
            "response": {"confirmed": True},
        }
    }],
}
engine.stream_query(user_id="smoke-test", session_id=session_id, message=resume_message)
```

## 6. Wire it into Claude Code via MCP (local machine only)

1. Edit `mcp_bridge/config.py` and replace `RESOURCE_NAME =
   "REPLACE_WITH_DEPLOYED_RESOURCE_NAME"` with the resource name from
   step 4.
2. Register it as a project-scoped MCP server by adding to this repo's
   `.mcp.json` (already done if you're reading this from the ops repo --
   see the root `.mcp.json`):
   ```json
   {
     "mcpServers": {
       "devops-3f9a": {
         "command": "C:\\path\\to\\devops-3f9a\\.venv\\Scripts\\python.exe",
         "args": ["C:\\path\\to\\devops-3f9a\\mcp_bridge\\server.py"]
       }
     }
   }
   ```
3. Restart Claude Code (or reload MCP servers) to pick up the new config.
4. From Claude Code, the tools `ask_devops_agent` and
   `confirm_devops_agent_action` should now be available -- ask a
   question, and if it triggers a mutating action, you'll get a pending
   confirmation you have to explicitly approve via the second tool
   before it actually runs.

## Known gaps to close before wider rollout

- **GKE IAM grant is outstanding** (step 2) -- every tool call will fail
  until this is done deliberately.
- **Broader team access** was deferred -- currently only the deploying
  account can invoke this engine. To add others, bind
  `roles/aiplatform.user` (or a narrower custom role scoped to
  `aiplatform.reasoningEngines.query`) to the relevant principal on the
  Reasoning Engine resource or the project.
- **Pod/deployment tools' network reachability** to each cluster's
  control plane hasn't been individually verified per cluster -- test
  `list_pods` against a real cluster in each of the 4 projects before
  relying on it.
