# devops-3f9a

GKE DevOps assistant for the LUZ ops estate, built on Google's Agent
Development Kit (ADK) and deployed to Vertex AI Agent Engine.

## Scope (enforced in code, not just the prompt)

- **Allowed projects:** `klara-nonprod`, `klara-performance`, `klara-infra`, `klara-repo`
- **Never:** `klara-prod` -- every tool call checks this via
  `devops_3f9a/config.py:assert_project_allowed`, independent of what the
  model decides to do.

## Capabilities

| Tool | Type | Confirmation required? |
|---|---|---|
| `list_clusters` | read | no |
| `get_cluster` | read | no |
| `list_node_pools` | read | no |
| `list_pods` | read | no |
| `get_pod_logs` | read | no |
| `resize_node_pool` | mutating | **yes** |
| `restart_deployment` | mutating | **yes** |
| `scale_deployment` | mutating | **yes** |

Mutating tools use ADK's built-in `require_confirmation=True` -- the
Agent Engine playground shows a native approve/reject prompt for these;
the MCP bridge (see below) surfaces the same pause as a two-step tool
call.

## Two access layers, two different prerequisites

1. **Cluster/node-pool tools** call the GKE **Container API**
   (`container.googleapis.com`) directly -- this always works regardless
   of a cluster's network configuration (private endpoint or not).
2. **Pod/deployment tools** call the target cluster's own **Kubernetes
   API** directly, using a bearer token minted from this agent's GCP
   credentials. This needs:
   - Network reachability from wherever the agent runs to each cluster's
     control plane endpoint.
   - The calling identity (the Agent Engine service account) to be
     authorized inside that cluster -- GKE's built-in IAM-to-RBAC
     authorization checks Cloud IAM roles (`roles/container.admin`,
     `roles/container.developer`, etc.) automatically for most clusters;
     a small number of clusters with custom/legacy authorization settings
     may additionally need an explicit `ClusterRoleBinding` for this
     agent's service account.

If pod/deployment tools fail with a connection or permission error, that's
this prerequisite, not a bug -- the agent will say so rather than pretend
the call succeeded.

## Prerequisites (GCP-side, one-time)

The Agent Engine runtime service account for whichever project it's
deployed into (e.g. `service-<project-number>@gcp-sa-aiplatform-re.iam.gserviceaccount.com`
for `klara-nonprod`) needs `roles/container.admin` (or narrower, e.g.
`roles/container.developer` for read + most mutations without full admin)
on each of the 4 allowed projects. **This has not been granted yet** as of
this agent's initial deployment -- tool calls will fail with a permission
error until it is. Granting cross-project IAM roles needs explicit
sign-off; see `DEPLOY.md` for the exact command.

## Files

- `devops_3f9a/agent.py` -- `root_agent` definition (model, tools, instruction).
- `devops_3f9a/prompt.py` -- the agent's system instruction.
- `devops_3f9a/config.py` -- the hard-coded project allowlist.
- `devops_3f9a/tools/gke_tools.py` -- all 8 tools.
- `deployment/deploy.py` -- create/update the Agent Engine deployment.
- `mcp_bridge/server.py` -- local MCP server exposing this agent to
  Claude Code (or any MCP client) on your machine.
- `DEPLOY.md` -- step-by-step instructions to deploy this agent from a
  local machine to Vertex AI Agent Engine.
