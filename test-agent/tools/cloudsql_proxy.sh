#!/usr/bin/env bash
# cloudsql_proxy.sh — run the Cloud SQL Auth Proxy so a GUI client (pgAdmin, DBeaver,
# psql) can connect to the Testing-Agent task-store Postgres over localhost.
#
# The task-store instance has NO public database access (no authorized networks); the
# ONLY way in is the IAM-authenticated Cloud SQL Auth Proxy — the same path the agents
# use (see deployments/cloudsql.tf and common/taskstore.py). This script:
#   1. downloads the proxy binary once (into tools/.bin, gitignored),
#   2. prints the pgAdmin connection settings incl. the password (pulled from Secret Manager),
#   3. runs the proxy in the FOREGROUND on 127.0.0.1:<PORT>.
# Leave it running while pgAdmin is connected; Ctrl-C stops it.
#
# Requires: gcloud with ADC (roles/cloudsql.client on the instance + secretmanager.secretAccessor
#           on the password secret), curl. No psql needed. Windows: run via Git Bash.
#
# Usage:
#   ./cloudsql_proxy.sh              # download proxy if needed, print conn info, start on :5432
#   PORT=6543 ./cloudsql_proxy.sh    # use a different local port (e.g. if 5432 is taken)
#   ./cloudsql_proxy.sh --info       # just print the pgAdmin connection settings, don't start
#
# pgAdmin → Register → Server → Connection tab:
#   Host=127.0.0.1  Port=<PORT>  Maintenance DB=<DB>  Username=<USER>  Password=<printed below>
#   SSL mode = disable  (the local hop is plaintext localhost; the proxy does TLS to Cloud SQL)
#
# Config (env overrides): INSTANCE, PORT, DB, DB_USER, SECRET, PROXY_VERSION, PROXY_URL
set -euo pipefail
cd "$(dirname "$0")"

INSTANCE="${INSTANCE:-klara-nonprod:europe-west6:kga-taskstore}"
PORT="${PORT:-5432}"
DB="${DB:-taskstore}"
USER_NAME="${DB_USER:-taskstore}"
SECRET="${SECRET:-kga-db-password}"
PROJECT="${INSTANCE%%:*}"

command -v gcloud >/dev/null || { echo "gcloud not on PATH"; exit 1; }
command -v curl   >/dev/null || { echo "curl not on PATH"; exit 1; }

# --- fetch the proxy binary once ---
# The Windows binary is published to Google's storage bucket (NOT as a GitHub release
# asset — those releases carry no binaries), versioned by tag. Resolve the latest tag
# from the GitHub API, or override with PROXY_VERSION / PROXY_URL.
BIN_DIR=".bin"
BIN="$BIN_DIR/cloud-sql-proxy.exe"
if [ ! -x "$BIN" ]; then
  VER="${PROXY_VERSION:-$(curl -fsSL https://api.github.com/repos/GoogleCloudPlatform/cloud-sql-proxy/releases/latest 2>/dev/null | grep -oE '"tag_name": *"[^"]+"' | cut -d'"' -f4)}"
  VER="${VER:-v2.25.4}"  # fallback if the API is unreachable / rate-limited
  URL="${PROXY_URL:-https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/$VER/cloud-sql-proxy.x64.exe}"
  echo "==> downloading Cloud SQL Auth Proxy $VER -> $BIN"
  mkdir -p "$BIN_DIR"
  curl -fL --progress-bar -o "$BIN" "$URL"
  chmod +x "$BIN"
fi

# --- password (from Secret Manager; the same version Cloud Run mounts) ---
echo "==> fetching DB password from Secret Manager ($SECRET)"
PASSWORD="$(gcloud secrets versions access latest --secret="$SECRET" --project="$PROJECT")"

cat <<INFO

  pgAdmin / DBeaver connection settings
  -------------------------------------
  Host            : 127.0.0.1
  Port            : $PORT
  Maintenance DB  : $DB
  Username        : $USER_NAME
  Password        : $PASSWORD
  SSL mode        : disable

INFO

[ "${1:-}" = "--info" ] && exit 0

echo "==> starting Cloud SQL Auth Proxy on 127.0.0.1:$PORT for $INSTANCE"
echo "    (leave this running; connect pgAdmin to the above; Ctrl-C to stop)"
exec "$BIN" "$INSTANCE" --address 127.0.0.1 --port "$PORT"
