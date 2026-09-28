# Running the Testing Agent FULLY LOCAL (docker-compose)

Run the entire v2 stack on your machine — no GCP, no deployed services. Everything the cloud version
uses has a local stand-in, and the LLM runs on **your local Claude subscription** (no API key).

```
Claude Code ──MCP──> gateway :8080 ──A2A──> kga · tpd · tev  (4th: admin)
                                              │
   worker (Redis Streams) ◄──── redis :6379 ──┤
   claude-proxy :8088 (your Claude sub) ◄──────┤ LLM
   ollama :11434 (embeddings only) ◄───────────┤
   postgres+pgvector :5432 ◄────────────────── tasks/sessions/prompts + memory recall
   minio :9000/:9001 (S3) ◄──────────────────── object store
```

## Prereqs
- **Rancher Desktop** (or Docker Desktop) running — the docker engine must be up.
- **~20 GB free disk** for a first build (images + Ollama embed model). Steady-state is smaller.
- Git Bash (Windows) — the scripts are bash.

## One-click
```bash
cd test-agent-v2
bash run-local.sh                 # builds missing images, starts everything, waits for the gateway
REBUILD=1 bash run-local.sh       # force-rebuild images after code changes (needs the disk headroom)
```
`run-local.sh` also runs the one-time Claude login if it detects you're not logged in.

## First-time Claude login (once)
The LLM is your Claude subscription, served by the `claude-proxy` sidecar. Log in once — it persists in
the `claude_config` volume:
```bash
docker compose exec claude-proxy claude      # then type /login, authorize in browser, /exit
docker compose exec claude-proxy claude -p "say ok"   # verify → prints "ok"
```

## Connect Claude Code to it
```bash
claude mcp add --transport http testing-agent-local http://localhost:8080/mcp
claude mcp list                    # testing-agent-local: connected
```
- Endpoint is **`http://localhost:8080/mcp`** (the `/mcp` path — the bare root won't work).
- **No token** — auth is disabled locally (`ALLOW_INSECURE=1`).
- Restart Claude Code so its tools load, then drive the pipeline (`gather_knowledge` → … → `implement_plan`).

## Config (`.env.compose`, copied from `.env.compose.example`)
| Knob | Default | Notes |
|------|---------|-------|
| LLM | `openai/claude-local` via claude-proxy | your subscription. **Non-local:** comment the `LITELLM_*` lines, use Ollama/Anthropic-API/Vertex. |
| Decisions | `TPD_DECISION_BACKEND=jev` | set `TYPESAFE_API_KEY` to activate JEV cloud; blank → falls back to the LLM. |
| Ollama chat model | *(unset)* | only pulls the 2GB chat model if `OLLAMA_CHAT_MODEL` is set (offline-LLM fallback). Embeddings (`nomic-embed-text`) always pulled. |
| Auth | `ALLOW_INSECURE=1`, blank tokens | local only. **Never** in a deployed env. Keep token lines comment-free (an inline `#` comment leaks into a blank value). |

## URLs
- Gateway / MCP: `http://localhost:8080/mcp`
- MinIO console: `http://localhost:9001` (user/pass from `.env.compose`)
- Ollama: `http://localhost:11434`
- Postgres: `localhost:5432`

## Common ops
```bash
docker compose ps                          # status
docker compose logs -f gateway             # tail a service
docker compose logs -f kga tpd tev worker
docker compose restart gateway
docker compose down                        # stop everything (volumes/login persist)
docker compose down -v                     # stop + WIPE volumes (loses login, db, minio)
```

## Troubleshooting
- **`/mcp` → ConnectionRefused / docker "cannot find the pipe"** → the engine is down. Start Rancher
  Desktop, then `bash run-local.sh` (or `docker compose up -d`). Not a stack problem.
- **`claude -p` → "Not logged in"** → re-run the login step above.
- **worker crash-loops on `redis_worker.py not found`** → the image is stale; `REBUILD=1 bash run-local.sh`.
- **`claude: executable file not found` in claude-proxy** → the npm claude-code binary is broken in slim;
  the image uses the official `install.sh` — `REBUILD=1` if you see this on an old image.
- **Everything 500s on the gateway** → check `docker exec test-agent-v2-gateway-1 printenv GATEWAY_BEARER_TOKEN`
  is empty; a leaked inline comment in `.env.compose` breaks the bearer check.
