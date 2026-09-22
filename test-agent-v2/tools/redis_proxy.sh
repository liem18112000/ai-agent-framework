#!/usr/bin/env bash
# redis_proxy.sh — reach the Testing-Agent benchmark cache (Memorystore Redis) from localhost so a
# GUI/CLI client (redis-cli, RedisInsight) can inspect it, mirroring tools/cloudsql_proxy.sh.
#
# WHY THIS IS DIFFERENT FROM cloudsql_proxy.sh: Memorystore has NO auth-proxy. A Basic-tier instance
# has only a PRIVATE VPC IP — unreachable from your laptop directly. The one supported path is to
# hop through a VM inside the VPC. This script IAP-tunnels an SSH port-forward through a tiny throwaway
# jump VM (created on demand, torn down with --teardown):
#
#   your laptop  --IAP SSH-->  redis-proxy-v2 (e2-micro in the VPC)  --TCP-->  <redis host>:6379
#   localhost:PORT  ==========================================================>  Memorystore
#
# This script:
#   1. resolves the Redis host/port from the instance (gcloud redis instances describe),
#   2. ensures the IAP-SSH firewall rule + the jump VM exist (idempotent; --no-address, no public IP),
#   3. prints the redis-cli / RedisInsight connection settings,
#   4. runs the IAP SSH tunnel in the FOREGROUND on 127.0.0.1:<PORT>.
# Leave it running while your client is connected; Ctrl-C stops it. Then `--teardown` deletes the VM.
#
# AUTH: our redis.tf leaves auth_enabled=false, so there is NO password (in-VPC private access only).
# If you set auth_enabled=true later, pass the AUTH string to your client (see `gcloud redis instances
# get-auth-string kga-v2-cache`).
#
# Requires: gcloud with ADC + roles/redis.viewer, roles/compute.instanceAdmin.v1,
#           roles/compute.securityAdmin (first run, to make the firewall rule),
#           roles/iap.tunnelResourceAccessor. Windows: run via Git Bash. Needs a local redis-cli to query.
#
# Usage:
#   ./redis_proxy.sh              # ensure VM, print conn info, start tunnel on :6379
#   PORT=6380 ./redis_proxy.sh    # different local port (e.g. if a local redis owns 6379)
#   ./redis_proxy.sh --info       # just print the connection settings, change nothing
#   ./redis_proxy.sh --teardown   # delete the jump VM (the firewall rule is left; harmless)
#
# Config (env overrides): INSTANCE, REGION, ZONE, NETWORK, PROXY_VM, PORT, PROJECT
set -euo pipefail
cd "$(dirname "$0")"

INSTANCE="${INSTANCE:-kga-v2-cache}"          # the Memorystore instance (redis.tf: ${name_prefix}-cache)
PORT="${PORT:-6379}"
NETWORK="${NETWORK:-default}"                  # must match redis_network in terraform.tfvars
PROXY_VM="${PROXY_VM:-redis-proxy-v2}"
FW_RULE="allow-iap-ssh-v2"

command -v gcloud >/dev/null || { echo "gcloud not on PATH"; exit 1; }

# region: env > terraform.tfvars > default (keeps this in sync with the deploy)
if [ -z "${REGION:-}" ]; then
  [ -f ../../deployments/test-agent-v2/terraform.tfvars ] &&
    REGION="$(sed -n 's/^[[:space:]]*region[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' ../../deployments/test-agent-v2/terraform.tfvars | head -1)"
  REGION="${REGION:-europe-west6}"
fi
ZONE="${ZONE:-${REGION}-a}"
PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
[ -n "$PROJECT" ] || { echo "no project — set PROJECT or 'gcloud config set project'"; exit 1; }

if [ "${1:-}" = "--teardown" ]; then
  echo "==> deleting jump VM $PROXY_VM ($ZONE)"
  gcloud compute instances delete "$PROXY_VM" --project "$PROJECT" --zone "$ZONE" --quiet || true
  echo "done. (firewall rule $FW_RULE left in place — delete with: gcloud compute firewall-rules delete $FW_RULE)"
  exit 0
fi

# --- resolve the Redis endpoint ---
echo "==> resolving Redis endpoint ($INSTANCE, $REGION)"
REDIS_HOST="$(gcloud redis instances describe "$INSTANCE" --project "$PROJECT" --region "$REGION" --format='value(host)')"
REDIS_PORT="$(gcloud redis instances describe "$INSTANCE" --project "$PROJECT" --region "$REGION" --format='value(port)')"
[ -n "$REDIS_HOST" ] || { echo "could not resolve Redis host — is deploy_redis=true applied?"; exit 1; }
REDIS_PORT="${REDIS_PORT:-6379}"

cat <<INFO

  redis-cli / RedisInsight connection settings
  --------------------------------------------
  Host       : 127.0.0.1
  Port       : $PORT
  Password   : (none — auth_enabled=false)
  Backing    : $REDIS_HOST:$REDIS_PORT  (Memorystore $INSTANCE)

  Try it (while this tunnel runs, in another shell):
    redis-cli -h 127.0.0.1 -p $PORT PING
    redis-cli -h 127.0.0.1 -p $PORT --scan --pattern 'memory/benchmarks/*'
    redis-cli -h 127.0.0.1 -p $PORT GET memory/benchmarks/<slug>.json

INFO

[ "${1:-}" = "--info" ] && exit 0

# --- ensure the IAP-SSH firewall rule (idempotent) ---
if ! gcloud compute firewall-rules describe "$FW_RULE" --project "$PROJECT" >/dev/null 2>&1; then
  echo "==> creating firewall rule $FW_RULE (allow IAP range -> tcp:22 on $NETWORK)"
  gcloud compute firewall-rules create "$FW_RULE" --project "$PROJECT" --network "$NETWORK" \
    --direction INGRESS --action allow --rules tcp:22 --source-ranges 35.235.240.0/20
fi

# --- ensure the jump VM (idempotent; no public IP, reachable only via IAP) ---
if ! gcloud compute instances describe "$PROXY_VM" --project "$PROJECT" --zone "$ZONE" >/dev/null 2>&1; then
  echo "==> creating jump VM $PROXY_VM (e2-micro, $ZONE, $NETWORK, no public IP) — ~30s"
  gcloud compute instances create "$PROXY_VM" --project "$PROJECT" --zone "$ZONE" \
    --machine-type e2-micro --network "$NETWORK" --no-address \
    --image-family debian-12 --image-project debian-cloud
  echo "    waiting for SSH to come up…"; sleep 20
fi

echo "==> tunneling 127.0.0.1:$PORT -> $REDIS_HOST:$REDIS_PORT via $PROXY_VM (IAP)"
echo "    (leave running; connect your client to 127.0.0.1:$PORT; Ctrl-C to stop; --teardown to delete the VM)"
exec gcloud compute ssh "$PROXY_VM" --project "$PROJECT" --zone "$ZONE" --tunnel-through-iap \
  -- -N -L "${PORT}:${REDIS_HOST}:${REDIS_PORT}"
