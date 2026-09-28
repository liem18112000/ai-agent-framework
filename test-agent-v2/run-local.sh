#!/usr/bin/env bash
# One-click local bring-up for the Testing-Agent stack — MinIO(S3) · Postgres/pgvector · Redis ·
# Redis-Streams worker · Ollama(embeddings) · 4 agents · gateway, with the LLM on your local Claude
# SUBSCRIPTION (claude-proxy). Idempotent — safe to re-run. Windows: run from Git Bash / `bash run-local.sh`.
#   REBUILD=1 ./run-local.sh   # force-rebuild images after code changes
set -euo pipefail
cd "$(dirname "$0")"
say() { printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; }

# 1. Prereqs -----------------------------------------------------------------
command -v docker >/dev/null || { echo "❌ docker not on PATH"; exit 1; }
docker info >/dev/null 2>&1 || { echo "❌ Docker engine not running — start Rancher/Docker Desktop first."; exit 1; }

# 2. Env ---------------------------------------------------------------------
if [ ! -f .env.compose ]; then
  cp .env.compose.example .env.compose
  say ".env.compose created from example — set your Atlassian creds in it for a real gather."
fi

# 3. Build + start (step 4 waits for readiness, so no --wait needed here) -----
say "Starting the stack (first run pulls images + Ollama models — can take a while)…"
if [ "${REBUILD:-0}" = "1" ]; then docker compose up -d --build; else docker compose up -d; fi

# 4. Wait for the gateway ----------------------------------------------------
say "Waiting for the gateway on :8080…"
for _ in $(seq 1 60); do
  docker compose exec -T gateway python -c "import urllib.request;urllib.request.urlopen('http://localhost:8080/livez')" >/dev/null 2>&1 && break
  sleep 3
done

# 5. Claude subscription login (only if needed) ------------------------------
say "Checking Claude subscription login…"
if docker compose exec -T claude-proxy claude -p "ok" --output-format json 2>/dev/null | grep -q "Not logged in"; then
  echo "  Not logged in — launching Claude: run /login, authorize in the browser, then exit the session."
  docker compose exec claude-proxy claude || true
else
  echo "  Already logged in ✓"
fi

# 6. Status ------------------------------------------------------------------
say "Stack status:"
docker compose ps --format 'table {{.Service}}\t{{.State}}\t{{.Status}}\t{{.Ports}}'
cat <<'EOF'

✅ Ready.
   MCP gateway : http://localhost:8080/   (no token — local dev)
   MinIO console: http://localhost:9001    Ollama: http://localhost:11434
   LLM = your Claude subscription (via claude-proxy). Re-login anytime:
     docker compose exec claude-proxy claude   → /login
EOF
