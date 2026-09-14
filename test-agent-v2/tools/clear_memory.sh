#!/usr/bin/env bash
# clear_memory.sh — truncate (delete every object in) the Testing-Agent GCS memory bank.
#
# The memory bank is a SINGLE GCS bucket ($GCS_BUCKET) rooted at memory/. Per the code
#   - common/memory/bank.py      (ROOT = "memory")
#   - test_plan_definition/memory/writers.py  (memory/test-plan/… namespace)
# the following subfolders hold the data files. This tool wipes all of them so the next
# pipeline run starts from a clean bank:
#
#   memory/index/       knowledge-index graph (json + md, CAS)    — KG bank
#   memory/notes/       jira/<KEY> · confluence/<id> · insight/<id> — KG bank
#   memory/refine/      Step 2: questions · answers · understanding · state — KG bank
#   memory/test-plan/   Step 3+4: plan · decisions · scenarios · steps · features — TPD writers
#   memory/runs/        run-logs (<ts>_run/refine/plan-<id>.md)   — both
#
# PREVIEW-FIRST: a plain run only reports what WOULD be deleted and changes nothing.
# Re-run with CONFIRM=1 to actually delete. Deletion is irreversible.
#
# Usage:
#   ./clear_memory.sh                        # preview: per-folder object counts, deletes nothing
#   CONFIRM=1 ./clear_memory.sh              # DELETE every object under all 5 folders
#   FOLDERS="refine test-plan" CONFIRM=1 ./clear_memory.sh   # limit to a subset of folders
#   GCS_BUCKET=other-bucket ./clear_memory.sh               # override the bucket
#
# Config resolution: GCS_BUCKET / GCP_PROJECT are taken from the environment, else from
# ../.env (the app's test-agent/.env — the same source knowledge_gathering/config.py reads).
#
# Requires: gcloud, authenticated with ADC (gcloud auth login / application-default login)
#           and storage.objects.list + .delete on the bucket.
set -euo pipefail
cd "$(dirname "$0")"

case "${1:-}" in
  -h|--help)
    sed -n '2,29p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
esac

command -v gcloud >/dev/null || { echo "gcloud not on PATH" >&2; exit 1; }

# Pull GCS_BUCKET / GCP_PROJECT from ../.env if not already exported (no secrets sourced).
ENV_FILE="../.env"
_from_env() { [ -f "$ENV_FILE" ] && grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true; }
: "${GCS_BUCKET:=$(_from_env GCS_BUCKET)}"
: "${GCP_PROJECT:=$(_from_env GCP_PROJECT)}"
: "${GCP_PROJECT:=$(_from_env VERTEX_PROJECT)}"

[ -n "${GCS_BUCKET:-}" ] || { echo "GCS_BUCKET not set and not found in $ENV_FILE" >&2; exit 1; }

ROOT="memory"
BASE="gs://$GCS_BUCKET/$ROOT"
read -r -a FOLDER_ARR <<< "${FOLDERS:-index notes refine test-plan runs}"

PROJECT_FLAG=()
[ -n "${GCP_PROJECT:-}" ] && PROJECT_FLAG=(--project "$GCP_PROJECT")

CONFIRM="${CONFIRM:-0}"
echo "Memory bank: $BASE/"
echo "Project:     ${GCP_PROJECT:-<gcloud default>}"
echo "Folders:     ${FOLDER_ARR[*]}"
if [ "$CONFIRM" = "1" ]; then
  echo "Mode:        DELETE (CONFIRM=1) — this is irreversible"
else
  echo "Mode:        PREVIEW (dry-run; set CONFIRM=1 to delete)"
fi
echo

total=0
for f in "${FOLDER_ARR[@]}"; do
  prefix="$BASE/$f/"
  # `**` matches all leaf objects recursively under the prefix; filter out any
  # zero-byte "folder" placeholder lines (those end in /). No match -> empty list.
  mapfile -t objs < <(gcloud storage ls "${PROJECT_FLAG[@]}" "$prefix**" 2>/dev/null | grep -E '^gs://.*[^/]$' || true)
  n=${#objs[@]}
  total=$((total + n))

  if [ "$n" -eq 0 ]; then
    printf '  %-11s empty (nothing to delete)\n' "$f/"
    continue
  fi

  if [ "$CONFIRM" = "1" ]; then
    printf '  %-11s deleting %d object(s)...\n' "$f/" "$n"
    gcloud storage rm --recursive "${PROJECT_FLAG[@]}" "$prefix" >/dev/null
    printf '  %-11s done — %d deleted\n' "$f/" "$n"
  else
    printf '  %-11s %d object(s) would be deleted\n' "$f/" "$n"
  fi
done

echo
if [ "$CONFIRM" = "1" ]; then
  echo "Cleared $total object(s) from $BASE/ across ${#FOLDER_ARR[@]} folder(s)."
else
  echo "PREVIEW only — $total object(s) across ${#FOLDER_ARR[@]} folder(s) would be deleted."
  echo "Re-run to delete:  CONFIRM=1 ./clear_memory.sh"
fi
