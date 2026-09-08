#!/usr/bin/env bash
# Local authenticated proxy to the PRIVATE A2A->MCP bridge on Cloud Run, so Claude
# (an MCP client) can reach it at http://localhost:$PORT/mcp with NO token in config:
# `gcloud run services proxy` authenticates with your ADC and refreshes automatically.
#
# Usage:
#   ./proxy.sh                 # start the proxy (foreground — keep it running while you use Claude)
#   PORT=8090 ./proxy.sh       # use a different local port
#   REGISTER=1 ./proxy.sh      # also `claude mcp add` the server, then start
#   SERVICE=... REGION=... NAME=... ./proxy.sh
#
# First run installs a one-time `Cloud Run Proxy` gcloud component (~20s before it binds).
# Then restart Claude Code so it loads the MCP server. Ctrl-C stops the proxy.
set -euo pipefail
cd "$(dirname "$0")"

SERVICE="${SERVICE:-mcp-gateway-v2}"          # Cloud Run service to proxy (the single MCP gateway)
PORT="${PORT:-8080}"
NAME="${NAME:-testing-agent}"                 # MCP server name to register with Claude
URL="http://localhost:${PORT}/mcp"

# region: env override > terraform.tfvars > default (keeps this in sync with the deploy)
if [ -z "${REGION:-}" ]; then
  [ -f terraform.tfvars ] &&
    REGION="$(sed -n 's/^[[:space:]]*region[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' terraform.tfvars | head -1)"
  REGION="${REGION:-europe-west6}"
fi

command -v gcloud >/dev/null || { echo "gcloud not on PATH"; exit 1; }

if [ "${REGISTER:-0}" = "1" ]; then
  if command -v claude >/dev/null; then
    echo "==> registering MCP server '$NAME' -> $URL"
    claude mcp add --transport http "$NAME" "$URL" || true
  else
    echo "note: claude CLI not found — register manually with the line below."
  fi
fi

echo "Register with Claude (if not already):"
echo "  claude mcp add --transport http $NAME $URL"
echo ""
echo "Proxying $SERVICE ($REGION) -> $URL   —   keep running; Ctrl-C to stop."
echo ""
exec gcloud run services proxy "$SERVICE" --region "$REGION" --port "$PORT" --quiet
