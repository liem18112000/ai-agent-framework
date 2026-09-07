#!/usr/bin/env bash
# Deploy the Testing Agent stack: provision infra (Terraform) → add secret versions
# → build+push the image → point Cloud Run at it. Covers both agents (knowledge-gathering
# and test-plan-definition) and their A2A->MCP bridges — one shared image, one shared bucket.
#
# Usage:
#   ./deploy.sh                 # full deploy
#   SKIP_BUILD=1 ./deploy.sh    # infra + secrets only (reuse current image)
#   PLAN=1 ./deploy.sh          # terraform plan only, change nothing
#
# Secrets are read from ../../test-agent-v1/.env (ATLASSIAN_API_TOKEN, A2A_BEARER_TOKEN,
# KGA_BRIDGE_BEARER_TOKEN, TPD_BRIDGE_BEARER_TOKEN) or the current shell env.
# Requires: terraform, gcloud (with ADC), a terraform.tfvars.
set -euo pipefail
cd "$(dirname "$0")"

command -v terraform >/dev/null || { echo "terraform not on PATH"; exit 1; }
command -v gcloud   >/dev/null || { echo "gcloud not on PATH"; exit 1; }
[ -f terraform.tfvars ] || { echo "terraform.tfvars missing (copy terraform.tfvars.example)"; exit 1; }

# Load secrets from the app .env if present (non-fatal if absent).
ENV_FILE="../../test-agent-v1/.env"
if [ -f "$ENV_FILE" ]; then
  set -a; . "$ENV_FILE"; set +a
fi

add_secret() {  # <secret-name> <env-var-name> — add a version only if the value is available
  local name="$1" val="${!2:-}"
  if [ -n "$val" ]; then
    printf '%s' "$val" | gcloud secrets versions add "$name" --data-file=- >/dev/null
    echo "    $name: version added"
  else
    echo "    $name: SKIPPED ($2 not set)"
  fi
}

echo "==> terraform init"
terraform init -input=false >/dev/null

if [ "${PLAN:-0}" = "1" ]; then
  terraform plan -input=false
  exit 0
fi

# --- secret containers FIRST ---
# A Cloud Run service that mounts `secret:latest` fails to start if the secret has no version
# yet. Since services + their secrets live in one config, create the secret CONTAINERS up front
# (targeted, idempotent) so we can add versions before the services that mount them are created.
echo "==> terraform apply (secret containers)"
terraform apply -auto-approve -input=false \
  -target='google_secret_manager_secret.atlassian_token' \
  -target='google_secret_manager_secret.bitbucket_app_password' \
  -target='google_secret_manager_secret.a2a_bearer' \
  -target='google_secret_manager_secret.bridge_bearer[0]' \
  -target='google_secret_manager_secret.tpd_bridge_bearer[0]'

echo "==> secret versions"
add_secret kga-atlassian-api-token      ATLASSIAN_API_TOKEN
add_secret kga-bitbucket-app-password   ATLASSIAN_BITBUCKET_APP_PASSWORD
add_secret kga-a2a-bearer-token         A2A_BEARER_TOKEN
add_secret kga-bridge-bearer-token      KGA_BRIDGE_BEARER_TOKEN
add_secret kga-tpd-bridge-bearer-token  TPD_BRIDGE_BEARER_TOKEN

# --- infra apply ---
# Preserve the image already deployed (read from state) so this apply never rolls the Cloud Run
# services back to var.image's default: an old/wrong image can fail to start and abort the deploy.
# The real image is built + applied below. On the first apply (empty state) this falls back to the
# variable default (a hello placeholder) so services can be created before the real image exists.
echo "==> terraform apply (infra)"
CURRENT_IMAGE=$(terraform state show 'module.kga.google_cloud_run_v2_service.this[0]' 2>/dev/null | awk -F'"' '/^[[:space:]]*image[[:space:]]*=/{print $2; exit}') || true  # module + count index; awk-exit SIGPIPEs terraform, pipefail+set-e would kill the deploy
if [ -n "$CURRENT_IMAGE" ]; then
  echo "    preserving deployed image: $CURRENT_IMAGE"
  terraform apply -auto-approve -input=false -var="image=$CURRENT_IMAGE"
else
  terraform apply -auto-approve -input=false
fi

# --- build + push image (unless SKIP_BUILD — then assume $IMAGE is already pushed),
#     then always point the services at $IMAGE from tfvars. ---
IMAGE="${IMAGE:-$(awk -F'"' '/^[[:space:]]*image[[:space:]]*=/{print $2; exit}' terraform.tfvars)}"
if [ "${SKIP_BUILD:-0}" != "1" ]; then
  echo "==> build + push $IMAGE"
  gcloud builds submit ../../test-agent-v1 --tag "$IMAGE" --suppress-logs
fi
echo "==> terraform apply (image=$IMAGE)"
terraform apply -auto-approve -input=false -var="image=$IMAGE"

echo ""
echo "Deployed."
echo "KGA agent:        $(terraform output -raw service_url)"
echo "KGA bridge (MCP): $(terraform output -raw bridge_url 2>/dev/null || echo n/a)"
TPD=$(terraform output -raw tpd_bridge_url 2>/dev/null || true)
if [ -n "$TPD" ] && [ "$TPD" != "null" ]; then
  echo "TPD agent:        $(terraform output -raw tpd_url)"
  echo "TPD bridge (MCP): $TPD"
  echo "Register w/ Claude: claude mcp add --transport http test-plan-definition $TPD"
fi
