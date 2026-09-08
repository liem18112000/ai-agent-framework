#!/usr/bin/env bash
#
# install-mcp.sh — register the v2 (ADK) Testing-Agent MCP servers with Claude Code.
#
#   knowledge-gathering   (Steps 1–2: gather + refine)
#   test-plan-definition  (Steps 3–4: define + implement)
#   test-evaluation       (Step 5: pack/plan scorer — app-ungated)
#
# "Deployed only": this points Claude Code at the DEPLOYED Cloud Run bridge URLs. Run ./deploy.sh
# first — the /mcp URLs come from `terraform output` in THIS directory (the live source of truth).
# ADK has no native MCP server, so the A2A→MCP bridge is Claude Code's native channel to the agents.
#
# This script:
#   1. reads the bearer tokens from ../../test-agent-v2/.env  (never hard-coded, never echoed),
#   2. resolves each /mcp URL from `terraform output` (or an env override),
#   3. registers each server via `claude mcp add --transport http` (idempotent remove-then-add).
#
# Usage:
#   ./install-mcp.sh                 # scope: local (current project)
#   ./install-mcp.sh --scope user    # available in every project
#   KGA_MCP_URL=… TPD_MCP_URL=… TEV_MCP_URL=… ./install-mcp.sh   # override URLs
#
# Env overrides (all optional): KGA_MCP_URL, TPD_MCP_URL, TEV_MCP_URL,
#   KGA_BRIDGE_BEARER_TOKEN, TPD_BRIDGE_BEARER_TOKEN (win over .env).
set -euo pipefail

# --- paths -----------------------------------------------------------------
# The script lives IN the terraform dir (deployments/test-agent-v2), so tf runs here.
TF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$TF_DIR/../.." && pwd)"           # ai-agentic-framework/
ENV_FILE="$REPO_DIR/test-agent-v2/.env"

SCOPE="local"
[ "${1:-}" = "--scope" ] && { SCOPE="${2:?--scope needs a value}"; }

# --- preflight -------------------------------------------------------------
command -v claude >/dev/null 2>&1 || {
  echo "ERROR: the 'claude' CLI is not on PATH. Install Claude Code first." >&2; exit 1; }

# --- load ONLY the two bearer keys from .env (env vars already set win) -----
read_env() {  # read_env KEY -> prints value from .env (first match), or nothing
  [ -f "$ENV_FILE" ] || return 0
  sed -n "s/^[[:space:]]*$1=//p" "$ENV_FILE" | head -1 | tr -d '\r'
}
: "${KGA_BRIDGE_BEARER_TOKEN:=$(read_env KGA_BRIDGE_BEARER_TOKEN)}"
: "${TPD_BRIDGE_BEARER_TOKEN:=$(read_env TPD_BRIDGE_BEARER_TOKEN)}"

# --- resolve URLs: env override > terraform output (no hard-coded fallback) --
tf_out() {  # tf_out OUTPUT_NAME
  command -v terraform >/dev/null 2>&1 || return 1
  terraform -chdir="$TF_DIR" output -raw "$1" 2>/dev/null
}
: "${KGA_MCP_URL:=$(tf_out bridge_url     || true)}"
: "${TPD_MCP_URL:=$(tf_out tpd_bridge_url || true)}"
: "${TEV_MCP_URL:=$(tf_out tev_bridge_url || true)}"

require_url() {  # require_url NAME URL
  if [ -z "$2" ] || [ "$2" = "null" ]; then
    echo "ERROR: no URL for $1 — deploy first (./deploy.sh) or set ${1//-/_}_MCP_URL." >&2
    return 1
  fi
}

# --- register one bearer-gated server (remove-then-add = idempotent) --------
add_server() {  # add_server NAME URL TOKEN
  local name="$1" url="$2" token="$3"
  require_url "$name" "$url" || return 1
  if [ -z "$token" ]; then
    echo "SKIP  $name — no bearer token (set in $ENV_FILE or export ${name//-/_}...)." >&2
    return 1
  fi
  echo "==> $name"
  echo "    url:   $url"
  echo "    token: ${token:0:4}…${token: -4} (${#token} chars)"
  claude mcp remove "$name" -s "$SCOPE" >/dev/null 2>&1 || true
  claude mcp add --transport http "$name" "$url" \
    --scope "$SCOPE" \
    --header "Authorization: Bearer $token"
}

# --- register an app-ungated server (test-evaluation: no bridge bearer) -----
add_open_server() {  # add_open_server NAME URL
  local name="$1" url="$2"
  require_url "$name" "$url" || return 1
  echo "==> $name (no app bearer — nonprod read-only scorer)"
  echo "    url:   $url"
  claude mcp remove "$name" -s "$SCOPE" >/dev/null 2>&1 || true
  claude mcp add --transport http "$name" "$url" --scope "$SCOPE"
}

echo "Registering v2 Testing-Agent MCP servers (scope: $SCOPE)"
echo
rc=0
add_server knowledge-gathering  "$KGA_MCP_URL" "${KGA_BRIDGE_BEARER_TOKEN:-}" || rc=1
echo
add_server test-plan-definition "$TPD_MCP_URL" "${TPD_BRIDGE_BEARER_TOKEN:-}" || rc=1
echo
add_open_server test-evaluation "$TEV_MCP_URL" || rc=1

echo
echo "Done. Restart Claude Code, then verify:"
echo "  claude mcp get knowledge-gathering"
echo "  claude mcp get test-plan-definition"
echo "  claude mcp get test-evaluation"
exit $rc
