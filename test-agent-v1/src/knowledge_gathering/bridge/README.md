# A2A → MCP bridge

Claude speaks **MCP**; the knowledge-gathering agent speaks **A2A**. This bridge sits between
them: it is an **MCP server** (stdio) that Claude launches, and an **A2A client** that talks to
the running agent over HTTP.

```
Claude ──MCP/stdio──▶ knowledge_gathering.bridge ──A2A/JSON-RPC over HTTP──▶ agent (uvicorn)
                       (this package)                                        /  message/send
```

Nothing on the agent server changes — the bridge runs **client-side**, next to Claude.

## Install

```bash
pip install ".[bridge]"     # adds the `mcp` runtime to the agent's deps
```

## Run

The agent must be reachable first (locally: `uvicorn knowledge_gathering.server:app`), then:

```bash
knowledge-gathering-bridge            # console script
# or, equivalently:
python -m knowledge_gathering.bridge  # stdio MCP server
```

### Configuration (env)

| Var | Default | Meaning |
|-----|---------|---------|
| `KGA_A2A_URL` | `http://localhost:8080/` | Base URL of the A2A agent. |
| `A2A_BEARER_TOKEN` | *(unset)* | Bearer token, if the agent's `BearerAuthMiddleware` enforces one. |

## Register with Claude

**Claude Desktop** — `claude_desktop_config.json`; **Claude Code** — `.mcp.json` (or `claude mcp add`).
Same shape either way:

```json
{
  "mcpServers": {
    "knowledge-gathering": {
      "command": "python",
      "args": ["-m", "knowledge_gathering.bridge"],
      "env": {
        "KGA_A2A_URL": "http://localhost:8080/",
        "A2A_BEARER_TOKEN": "…optional…"
      }
    }
  }
}
```

(Point `command` at the venv's Python, or use the `knowledge-gathering-bridge` console script, so
the `mcp` dependency resolves.)

## Run on Cloud Run (remote MCP)

stdio can't be hosted — a remote container has no stdin/stdout link to Claude. To host the
bridge, serve it over **Streamable HTTP** and register it with Claude as a *remote connector*:

```bash
KGA_BRIDGE_TRANSPORT=http python -m knowledge_gathering.bridge   # serves MCP at 0.0.0.0:$PORT/mcp
```

A Cloud Run service exposes **one** port, so the agent and the bridge are **separate services**
(recommended — one process per container). The same image runs either; only the command + env differ.

```bash
# 1) agent service (default CMD in the Dockerfile)
gcloud run deploy kg-agent  --image "$IMG" --region "$REGION" \
    --set-env-vars ATLASSIAN_BASE_URL=…,ATLASSIAN_EMAIL=…,GCS_BUCKET=… \
    --set-secrets  ATLASSIAN_API_TOKEN=…,A2A_BEARER_TOKEN=… \
    --min-instances 1 --no-cpu-throttling            # refine keeps task state in memory

# 2) bridge service — talks A2A to the agent, serves MCP over HTTP
gcloud run deploy kg-bridge --image "$IMG" --region "$REGION" \
    --command python --args=-m,knowledge_gathering.bridge \
    --set-env-vars KGA_BRIDGE_TRANSPORT=http,KGA_A2A_URL=https://kg-agent-….run.app/ \
    --set-secrets  A2A_BEARER_TOKEN=… \              # forwarded on each A2A call
    --min-instances 1 --session-affinity --no-cpu-throttling
```

Register the bridge with Claude (Claude Code shown; on claude.ai add a custom connector with the URL):

```bash
claude mcp add --transport http knowledge-gathering https://kg-bridge-….run.app/mcp
```

### Statefulness on Cloud Run
Multi-turn `refine` keeps state in three single-instance places — the agent's `InMemoryTaskStore`,
the A2A task, and the bridge's `context_id → task_id` map. So for refine, run **both** services with
`--min-instances 1 --session-affinity --no-cpu-throttling` (don't scale to zero). One-shot `gather`
has no such constraint. `KGA_BRIDGE_STATELESS=1` drops the bridge's MCP session layer but does **not**
lift the refine constraint above.

### Auth
The bridge URL can drive the agent, so protect it: keep the Cloud Run service private behind an
ID-token proxy / IAP, or enforce your own token. The bridge→agent hop uses `A2A_BEARER_TOKEN`.

## Tools exposed

| MCP tool | A2A operation | Notes |
|----------|---------------|-------|
| `gather_knowledge(seed, depth=2, context_id?)` | one-shot gather | Returns a `context_id` to reuse in `refine`. |
| `refine(context_id, answer?)` | multi-turn interrogation | Call once to get the question round; call again with `answer="Q-…: choice"` per round until it reports **Refinement complete**. |
| `get_questions(context_id)` | read helper | Open/answered questions. |
| `get_understanding(context_id)` | read helper | Latest understanding brief. |
| `agent_card()` | fetch Agent Card | Name, version, advertised skills. |
| `send_raw(text, context_id?, task_id?)` | raw `message/send` | Escape hatch for anything the typed tools don't cover. |

### Why `refine` is stateful

A2A refinement is a paused **Task**: the agent replies `input-required` and the client must answer
on the *same* `taskId` + `contextId`. MCP tool calls are independent, so the bridge remembers
`context_id → task_id` in-process and clears it when the task completes — so from Claude's side it's
just: `refine(ctx)` → answer → answer → done.
