#!/usr/bin/env bash
# Rotate the Testing-Agent bearer tokens and revoke the old ones.
#
# Rotates BOTH gates, because either one alone is a way in:
#   * kga-v2-gateway-bearer-token — Claude/MCP client  →  mcp-gateway-v2   (the user-facing gate)
#   * kga-v2-a2a-bearer-token     — gateway            →  the A2A agents   (the agents are deployed
#     with allUsers invoker, so this token IS a direct bypass of the gateway — rotating only the
#     gateway token leaves every agent reachable by whoever still holds the old A2A one)
#
# WHY THE REVISION ROLL (step 4): every service mounts the secrets as `:latest`, and Cloud Run
# resolves that at INSTANCE START, not per request. With min_instances=1 nothing ever restarts on
# its own, so adding a new secret version locks out precisely nobody until a new revision rolls.
# Adding the version is the easy half; step 4 is the half that actually revokes access.
#
# Usage:
#   ./rotate_a2a_bearer_key.sh              # rotate, revoke, roll, verify
#   DRY_RUN=1 ./rotate_a2a_bearer_key.sh    # print every action, change nothing, generate no tokens
#
# Writes the new values to ../../test-agent-v2/.env (backup at .env.bak) so deploy.sh and
# install-mcp.sh pick them up. Requires: gcloud (ADC), terraform state, openssl, curl.
set -euo pipefail
cd "$(dirname "$0")"

# $PROJECT, $REGION, $ENV_FILE (already sourced) and secret_add_version() come from here.
. ./lib.sh

GW_SECRET="kga-v2-gateway-bearer-token"
A2A_SECRET="kga-v2-a2a-bearer-token"

# Every service that mounts either bearer. tpd-gen-worker only exists when deploy_workers=true —
# a missing service is a warning, never fatal.
SERVICES=(
  mcp-gateway-v2
  knowledge-gathering-agent-v2
  test-plan-definition-agent-v2
  test-evaluation-agent-v2
  admin-agent-v2
  test-executor-agent-v2
  tpd-gen-worker
)

DRY_RUN="${DRY_RUN:-0}"
run() {  # echo + execute, or echo only under DRY_RUN
  if [ "$DRY_RUN" = "1" ]; then echo "    [dry-run] $*"; else "$@"; fi
}
mask() { [ ${#1} -ge 8 ] && echo "${1:0:4}…${1: -4} (${#1} chars)" || echo "(short)"; }

command -v gcloud  >/dev/null || { echo "gcloud not on PATH"; exit 1; }
command -v openssl >/dev/null || { echo "openssl not on PATH"; exit 1; }
[ -f "$ENV_FILE" ] || { echo "ERROR: $ENV_FILE missing — nowhere to save the new tokens"; exit 1; }

# lib.sh already sourced .env, so the outgoing token is just a variable. Keep it — step 5 needs it
# to prove the old token stopped working.
OLD_GW="${GATEWAY_BEARER_TOKEN:-}"

# ---------------------------------------------------------------------------
# 1. new values
# ---------------------------------------------------------------------------
echo "==> generating new tokens"
if [ "$DRY_RUN" = "1" ]; then
  NEW_GW="<dry-run>"; NEW_A2A="<dry-run>"
  echo "    [dry-run] openssl rand -hex 32  (x2)"
else
  NEW_GW="$(openssl rand -hex 32)"
  NEW_A2A="$(openssl rand -hex 32)"
  echo "    gateway: $(mask "$NEW_GW")"
  echo "    a2a:     $(mask "$NEW_A2A")"
fi

# ---------------------------------------------------------------------------
# 2. add the versions (lib.sh's secret_add_version feeds the value on stdin, so it never lands in
#    an argv the process list can leak)
# ---------------------------------------------------------------------------
echo "==> adding secret versions"
add_version() {  # <secret> <value> — secret_add_version + DRY_RUN + a progress line
  if [ "$DRY_RUN" = "1" ]; then
    echo "    [dry-run] secret_add_version $1"
  else
    echo "    $1: version $(secret_add_version "$1" "$2")"
  fi
}
add_version "$GW_SECRET"  "$NEW_GW"
add_version "$A2A_SECRET" "$NEW_A2A"

# ---------------------------------------------------------------------------
# 3. save locally — deploy.sh and install-mcp.sh both source this file
#
# A2A_BEARER_TOKEN is usually ABSENT here, which is why deploy.sh has been printing
# "kga-v2-a2a-bearer-token: SKIPPED (A2A_BEARER_TOKEN not set)" on every deploy. Append it.
# ---------------------------------------------------------------------------
echo "==> writing $ENV_FILE (backup: $ENV_FILE.bak)"
if [ "$DRY_RUN" = "1" ]; then
  echo "    [dry-run] set GATEWAY_BEARER_TOKEN + A2A_BEARER_TOKEN"
else
  cp "$ENV_FILE" "$ENV_FILE.bak"
  awk -v gw="$NEW_GW" -v a2a="$NEW_A2A" '
    /^GATEWAY_BEARER_TOKEN=/ { print "GATEWAY_BEARER_TOKEN=" gw; next }
    /^A2A_BEARER_TOKEN=/     { print "A2A_BEARER_TOKEN=" a2a; seen=1; next }
                             { print }
    END { if (!seen) print "A2A_BEARER_TOKEN=" a2a }
  ' "$ENV_FILE.bak" > "$ENV_FILE"
  grep -cE '^(GATEWAY|A2A)_BEARER_TOKEN=' "$ENV_FILE" | sed 's/^/    tokens written: /'
fi

# ---------------------------------------------------------------------------
# 4a. revoke — disable every older ENABLED version so the old value can't be read back
#     (safe because nothing pins a version; all services mount `:latest`)
# ---------------------------------------------------------------------------
echo "==> disabling superseded versions"
for s in "$GW_SECRET" "$A2A_SECRET"; do
  # gc, not gcloud — these values become command ARGUMENTS, and a captured \r makes the resource
  # name fail to parse while still looking correct in the error message.
  latest="$(gc secrets versions list "$s" --project "$PROJECT" \
              --filter=state=ENABLED --sort-by=~name --limit=1 --format='value(name)')"
  [ -n "$latest" ] || { echo "    $s: no enabled versions?! skipping"; continue; }
  n=0
  for v in $(gc secrets versions list "$s" --project "$PROJECT" \
               --filter=state=ENABLED --format='value(name)'); do
    [ "$v" = "$latest" ] && continue
    run gcloud secrets versions disable "$v" --secret="$s" --project "$PROJECT" --quiet
    n=$((n + 1))
  done
  # Under DRY_RUN step 2 never ran, so `latest` is still the CURRENT token — say so, otherwise
  # the preview reads as "it keeps the token you are trying to revoke".
  if [ "$DRY_RUN" = "1" ]; then
    # n excludes today's newest; a real run adds one on top, so that newest gets disabled too.
    echo "    $s: (dry-run) newest today is $latest — a real run adds $((latest + 1)) first, then disables the $((n + 1)) versions enabled today"
  else
    echo "    $s: kept $latest, disabled $n older"
  fi
done

# ---------------------------------------------------------------------------
# 4b. revoke, for real — roll a new revision on every consumer so it re-reads `:latest`.
#     The BEARER_ROTATED_AT stamp exists only to force the new revision; terraform drops it on
#     the next apply, which is harmless — by then `:latest` already IS the new value.
# ---------------------------------------------------------------------------
echo "==> rolling revisions (this is what revokes the old tokens)"
stamp="$(date +%s)"
for s in "${SERVICES[@]}"; do
  if ! gcloud run services describe "$s" --region "$REGION" --project "$PROJECT" >/dev/null 2>&1; then
    echo "    $s: not deployed, skipped"
    continue
  fi
  run gcloud run services update "$s" --region "$REGION" --project "$PROJECT" \
      --update-env-vars="BEARER_ROTATED_AT=$stamp" --quiet >/dev/null
  echo "    $s: new revision"
done

# ---------------------------------------------------------------------------
# 5. verify — the old gateway token must now be rejected, the new one accepted.
#    A bare POST is not valid MCP, so the NEW token is expected to come back 4xx-but-not-401:
#    anything other than 401/403 proves auth passed and the request died at the protocol layer.
# ---------------------------------------------------------------------------
if [ "$DRY_RUN" = "1" ]; then
  echo "==> [dry-run] skipping verification"
  exit 0
fi
GW_URL="$(terraform output -raw gateway_url 2>/dev/null | tr -d '\r' || true)"
if [ -z "$GW_URL" ] || ! command -v curl >/dev/null; then
  echo "==> verification skipped (no gateway_url output or no curl)"
  exit 0
fi

echo "==> verifying $GW_URL"
probe() { curl -s -o /dev/null -w '%{http_code}' --max-time 30 -X POST "$GW_URL" \
            -H "Authorization: Bearer $1" -H 'Content-Type: application/json' -d '{}'; }

rc=0
if [ -n "$OLD_GW" ]; then
  code="$(probe "$OLD_GW")"
  case "$code" in
    401|403) echo "    old token → $code  REJECTED ✔" ;;
    5??|000) echo "    old token → $code  INCONCLUSIVE — edge error, never reached the app (service disabled? scalingMode=manual)"; rc=1 ;;
    *)       echo "    old token → $code  STILL ACCEPTED ✘ — revision may not have rolled yet"; rc=1 ;;
  esac
else
  echo "    old token → not found in .env, nothing to check"
fi

code="$(probe "$NEW_GW")"
case "$code" in
  401|403) echo "    new token → $code  REJECTED ✘ — gateway has not picked up the new version"; rc=1 ;;
  5??|000) echo "    new token → $code  INCONCLUSIVE — edge error, never reached the app (service disabled? scalingMode=manual)"; rc=1 ;;
  *)       echo "    new token → $code  ACCEPTED ✔" ;;
esac

[ $rc -eq 0 ] && echo "==> done. Run ./install-mcp.sh to re-register the MCP client." \
              || echo "==> FAILED verification — see above."
exit $rc
