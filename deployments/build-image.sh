#!/usr/bin/env bash
# Build the test-agent container and push it to Artifact Registry.
#
# Default: Cloud Build (builds remotely, no local docker daemon needed).
#   ./build-image.sh
# Local docker build + push instead:
#   LOCAL=1 ./build-image.sh
# Override the target image:
#   IMAGE=<region>-docker.pkg.dev/<project>/<repo>/<name>:<tag> ./build-image.sh
set -euo pipefail
cd "$(dirname "$0")"

RAW_IMAGE="${IMAGE:-europe-west6-docker.pkg.dev/klara-repo/artifact-registry-container-images/test-agent:latest}"
# Collapse accidental double slashes — Docker/AR reject empty path components ("//").
IMAGE="$(printf '%s' "$RAW_IMAGE" | sed 's#//\+#/#g')"
[ "$IMAGE" != "$RAW_IMAGE" ] && echo "note: normalized image '$RAW_IMAGE' -> '$IMAGE'"

CONTEXT="../test-agent"                # holds the Dockerfile
REGISTRY_HOST="${IMAGE%%/*}"           # e.g. europe-west6-docker.pkg.dev

[ -f "$CONTEXT/Dockerfile" ] || { echo "Dockerfile not found at $CONTEXT"; exit 1; }
command -v gcloud >/dev/null || { echo "gcloud not on PATH"; exit 1; }

if [ "${LOCAL:-0}" = "1" ]; then
  command -v docker >/dev/null || { echo "docker not on PATH"; exit 1; }
  echo "==> gcloud auth configure-docker $REGISTRY_HOST"
  gcloud auth configure-docker "$REGISTRY_HOST" --quiet
  echo "==> docker build -t $IMAGE $CONTEXT"
  docker build -t "$IMAGE" "$CONTEXT"
  echo "==> docker push $IMAGE"
  docker push "$IMAGE"
else
  echo "==> gcloud builds submit $CONTEXT --tag $IMAGE"
  # --suppress-logs: don't stream logs (avoids the "can only stream if Viewer/Owner / VPC-SC"
  # error); gcloud still waits for the build and reports its final status.
  gcloud builds submit "$CONTEXT" --tag "$IMAGE" --suppress-logs
fi

echo ""
echo "pushed: $IMAGE"
echo "point Cloud Run at it:  terraform apply -var=\"image=$IMAGE\""
