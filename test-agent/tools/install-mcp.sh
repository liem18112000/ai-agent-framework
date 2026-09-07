#!/usr/bin/env bash
#
# install-mcp.sh — register BOTH Testing-Agent MCP servers with Claude Code.
#
#   knowledge-gathering   (Steps 1–2: gather + refine)
#   test-plan-definition  (Steps 3–4: define + implement)
#
# Both bridges run bearer-gated on Cloud Run. This script:
#   1. reads the bearer tokens from test-agent/.env  (never hard-coded, never echoed),
#   2. resolves each /mcp URL from `terraform output` (the live source of truth),
#   3. registers each server via `claude mcp add --transport http` (idempotent).
#
# Usage:
#   ./install-mcp.sh                 # scope: local (current project)
#   ./install-mcp.sh --scope user    # available in every project
#   KGA_MCP_URL=… TPD_MCP_URL=… ./install-mcp.sh   # override URLs
#
# Env overrides (all optional): KGA_MCP_URL, TPD_MCP_URL,
#   KGA_BRIDGE_BEARER_TOKEN, TPD_BRIDGE_BEARER_TOKEN (win over .env).
set -euo pipefail

# --- paths -----------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"          # test-agent/
REPO_DIR="$(cd "$AGENT_DIR/.." && pwd)"            # ai-agentic-framework/
DEPLOY_DIR="$REPO_DIR/deployments"
ENV_FILE="$AGENT_DIR/.env"

SCOPE="local"
[ "${1:-}" = "--scope" ] && { SCOPE="${2:?--scope needs a value}"; }

# Documented fallbacks — used only if `terraform output` is unavailable.
KGA_MCP_URL_DEFAULT="https://knowledge-gathering-agent-q5rqhzn2uq-oa.a.run.app/mcp"
TPD_MCP_URL_DEFAULT="https://test-plan-definition-agent-q5rqhzn2uq-oa.a.run.app/mcp"
TEV_MCP_URL_DEFAULT="https://test-evaluation-agent-q5rqhzn2uq-oa.a.run.app/mcp"

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

# --- resolve URLs: env override > terraform output > documented default -----
tf_out() {  # tf_out OUTPUT_NAME
  command -v terraform >/dev/null 2>&1 || return 1
  [ -d "$DEPLOY_DIR" ] || return 1
  terraform -chdir="$DEPLOY_DIR" output -raw "$1" 2>/dev/null
}
: "${KGA_MCP_URL:=$(tf_out bridge_url     || echo "$KGA_MCP_URL_DEFAULT")}"
: "${TPD_MCP_URL:=$(tf_out tpd_bridge_url || echo "$TPD_MCP_URL_DEFAULT")}"
: "${TEV_MCP_URL:=$(tf_out tev_bridge_url || echo "$TEV_MCP_URL_DEFAULT")}"

# --- register one server (remove-then-add = idempotent) --------------------
add_server() {  # add_server NAME URL TOKEN
  local name="$1" url="$2" token="$3"
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

# --- register an app-ungated server (test-evaluation: no bridge bearer) ----
add_open_server() {  # add_open_server NAME URL
  local name="$1" url="$2"
  echo "==> $name (no app bearer — nonprod read-only scorer)"
  echo "    url:   $url"
  claude mcp remove "$name" -s "$SCOPE" >/dev/null 2>&1 || true
  claude mcp add --transport http "$name" "$url" --scope "$SCOPE"
}

echo "Registering Testing-Agent MCP servers (scope: $SCOPE)"
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
