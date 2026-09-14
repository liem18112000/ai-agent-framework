# Quickstart: deploy devops-3f9a to Vertex AI Agent Engine

Condensed copy-paste checklist for deploying `devops-3f9a` to
`klara-nonprod` and verifying it in the console. For the full
explanation of every step (why the `extra_packages` path matters, the
confirmation-resume flow, etc.), see [`DEPLOY.md`](DEPLOY.md).

Console (verify deployment here after step 4):
https://console.cloud.google.com/agent-platform/runtimes?project=klara-nonprod

## 0. Prerequisites

- Python 3.12 and [`uv`](https://docs.astral.sh/uv/)
- `gcloud` CLI authenticated, with `roles/aiplatform.user` (or broader)
  on `klara-nonprod`
- `aiplatform.googleapis.com` enabled on `klara-nonprod`

```powershell
gcloud auth login
gcloud auth application-default login
```

## 1. Install pinned dependencies

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

## 2. One-time GCP setup (skip if already done)

```powershell
gcloud storage buckets create gs://klara-nonprod-agent-engine-staging-us-central1 `
  --project=klara-nonprod --location=us-central1 --uniform-bucket-level-access
```

GKE IAM grant for the Agent Engine runtime service account (needed
before pod/deployment tools work -- run deliberately, it's a real
cross-project IAM change):

```bash
for proj in klara-nonprod klara-performance klara-infra klara-repo; do
  gcloud projects add-iam-policy-binding "$proj" \
    --member="serviceAccount:service-<PROJECT_NUMBER>@gcp-sa-aiplatform-re.iam.gserviceaccount.com" \
    --role="roles/container.admin"
done
```

Get `<PROJECT_NUMBER>` (klara-nonprod's project number):

```bash
gcloud projects describe klara-nonprod --format='value(projectNumber)'
```

## 3. Verify the package imports cleanly (local)

```powershell
$env:PYTHONPATH = (Get-Location)
.\.venv\Scripts\python.exe -c "from devops_3f9a.agent import root_agent; print(root_agent.name, [t.name for t in root_agent.tools])"
```

## 4. Deploy

Run from `devops-3f9a/` (project root), not `deployment/`:

```powershell
$env:PYTHONPATH = (Get-Location)
.\.venv\Scripts\python.exe deployment\deploy.py
```

Save the printed resource name:
`projects/<num>/locations/us-central1/reasoningEngines/<id>`

To update an existing deployment instead of creating a new one:

```powershell
.\.venv\Scripts\python.exe deployment\deploy.py --update "projects/<num>/locations/us-central1/reasoningEngines/<id>"
```

## 5. Verify in the console

Open:
https://console.cloud.google.com/agent-platform/runtimes?project=klara-nonprod

Confirm the reasoning engine ID from step 4 shows up in the runtimes
list, with a healthy status.

## 6. Smoke-test

```python
import vertexai
from vertexai import agent_engines

vertexai.init(project="klara-nonprod", location="us-central1")
engine = agent_engines.get("projects/<num>/locations/us-central1/reasoningEngines/<id>")

for event in engine.stream_query(user_id="smoke-test", message="List clusters in klara-nonprod"):
    print(event)
```

If GKE IAM access (step 2) hasn't been granted yet, expect a
permission error here -- that confirms the deployment itself is
healthy and only the IAM grant is outstanding.

## 7. Wire into Claude Code via MCP (local machine only)

1. Edit `mcp_bridge/config.py`, set `RESOURCE_NAME` to the resource
   name from step 4.
2. Confirm the root `.mcp.json` registers `devops-3f9a` (already done
   in this repo).
3. Restart Claude Code / reload MCP servers.
4. Tools `ask_devops_agent` and `confirm_devops_agent_action` should
   now be available.

See `DEPLOY.md` for the full walkthrough and known gaps (IAM grant
outstanding, team access, per-cluster network reachability).
