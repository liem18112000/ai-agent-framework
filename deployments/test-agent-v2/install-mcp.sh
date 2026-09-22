#!/usr/bin/env bash
#
# install-mcp.sh — register the SINGLE v2 MCP gateway with Claude Code.
#
# The gateway (mcp-gateway-v2) fronts all three agents (knowledge-gathering, test-plan-definition,
# test-evaluation) over A2A, so Claude connects to ONE endpoint that exposes every tool. (Before G2
# there were three per-agent bridges; they were removed.)
#
# This script:
#   1. reads GATEWAY_BEARER_TOKEN from ../../test-agent-v2/.env (never hard-coded, never echoed),
#   2. resolves the /mcp URL from `terraform output gateway_url` (or an env override),
#   3. registers it via `claude mcp add --transport http` (idempotent remove-then-add).
#
# Usage:
#   ./install-mcp.sh                 # scope: local (current project)
#   ./install-mcp.sh --scope user    # available in every project
#   GATEWAY_MCP_URL=… ./install-mcp.sh          # override the URL
#   GATEWAY_BEARER_TOKEN=… ./install-mcp.sh     # override the token (wins over .env)
set -euo pipefail

TF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"     # = the terraform dir
REPO_DIR="$(cd "$TF_DIR/../.." && pwd)"                    # ai-agentic-framework/
ENV_FILE="$REPO_DIR/test-agent-v2/.env"
NAME="testing-agent"

SCOPE="local"
[ "${1:-}" = "--scope" ] && { SCOPE="${2:?--scope needs a value}"; }

command -v claude >/dev/null 2>&1 || {
  echo "ERROR: the 'claude' CLI is not on PATH. Install Claude Code first." >&2; exit 1; }

read_env() {  # read_env KEY -> value from .env (first match), or nothing
  [ -f "$ENV_FILE" ] || return 0
  sed -n "s/^[[:space:]]*$1=//p" "$ENV_FILE" | head -1 | tr -d '\r'
}
: "${GATEWAY_BEARER_TOKEN:=$(read_env GATEWAY_BEARER_TOKEN)}"

tf_out() {  # tf_out OUTPUT_NAME
  command -v terraform >/dev/null 2>&1 || return 1
  terraform -chdir="$TF_DIR" output -raw "$1" 2>/dev/null
}
: "${GATEWAY_MCP_URL:=$(tf_out gateway_url || true)}"

if [ -z "$GATEWAY_MCP_URL" ] || [ "$GATEWAY_MCP_URL" = "null" ]; then
  echo "ERROR: no gateway URL — deploy first (./deploy.sh) or set GATEWAY_MCP_URL." >&2
  exit 1
fi

echo "==> $NAME (single MCP gateway; fronts the 3 A2A agents)"
echo "    url:   $GATEWAY_MCP_URL"
claude mcp remove "$NAME" -s "$SCOPE" >/dev/null 2>&1 || true
if [ -n "${GATEWAY_BEARER_TOKEN:-}" ]; then
  echo "    token: ${GATEWAY_BEARER_TOKEN:0:4}…${GATEWAY_BEARER_TOKEN: -4} (${#GATEWAY_BEARER_TOKEN} chars)"
  claude mcp add --transport http "$NAME" "$GATEWAY_MCP_URL" \
    --scope "$SCOPE" --header "Authorization: Bearer $GATEWAY_BEARER_TOKEN"
else
  echo "    (no bearer token set — the gateway is open)"
  claude mcp add --transport http "$NAME" "$GATEWAY_MCP_URL" --scope "$SCOPE"
fi

echo
echo "Done. Restart Claude Code, then verify:  claude mcp get $NAME"
