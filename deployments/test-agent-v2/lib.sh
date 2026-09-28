#!/usr/bin/env bash
# Shared helpers for the test-agent-v2 deployment scripts (deploy.sh, rotate_a2a_bearer_key.sh).
# SOURCED, never executed: `. ./lib.sh` from a script that has already cd'd to this directory.
#
# Provides:
#   $PROJECT / $REGION   — GCP target; export either before sourcing to override
#   $ENV_FILE            — the app .env, already sourced into the environment when it exists, so
#                          anything defined in it (ATLASSIAN_API_TOKEN, GATEWAY_BEARER_TOKEN, …)
#                          is readable as a normal variable after this file is sourced
#   secret_add_version   — <secret> <value>   → adds a version, prints the new version name
#   add_secret           — <secret> <env-var> → secret_add_version, or SKIPPED when the var is unset

PROJECT="${PROJECT:-klara-nonprod}"
REGION="${REGION:-europe-west6}"

# Load secrets from the app .env if present (non-fatal if absent).
ENV_FILE="${ENV_FILE:-../../test-agent-v2/.env}"
if [ -f "$ENV_FILE" ]; then
  set -a; . "$ENV_FILE"; set +a
fi

# Windows gcloud emits CRLF. `$(...)` strips the trailing \n but NOT the \r, so a captured value
# silently becomes "59\r" and every command it is fed into fails with a format error that names a
# string which looks perfectly valid in the terminal. Capture through this, never bare gcloud.
# (pipefail is on in the callers, so gcloud's exit status still wins over tr's.)
gc() { gcloud "$@" | tr -d '\r'; }

# The value arrives on stdin, never in argv — argv is readable by any process on the box.
# `versions add` returns the FULL resource path under value(name) while `versions list` returns a
# bare number; strip to the bare version so both agree and the result is usable as an argument.
secret_add_version() {  # <secret-name> <value> → prints the new version number
  printf '%s' "$2" | gc secrets versions add "$1" \
    --project "$PROJECT" --data-file=- --format='value(name)' | sed 's#.*/##'
}

add_secret() {  # <secret-name> <env-var-name> — add a version only if the value is available
  local name="$1" val="${!2:-}"
  if [ -n "$val" ]; then
    echo "    $name: version $(secret_add_version "$name" "$val") added"
  else
    echo "    $name: SKIPPED ($2 not set)"
  fi
}
