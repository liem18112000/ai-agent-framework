#!/usr/bin/env bash
# Sync every git submodule declared in .gitmodules to the tip of its tracked
# branch (submodule.<name>.branch if set, else the remote's default HEAD
# branch). Skips any submodule with uncommitted changes instead of
# clobbering them. Does NOT commit the moved pointers into the superproject
# — review `git status` / `git diff --submodule` and commit that yourself.

set -uo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

if [ ! -f .gitmodules ]; then
  echo "No .gitmodules file at $repo_root — nothing to sync."
  exit 0
fi

echo "Syncing submodule registration and initializing any missing ones..."
git submodule sync --recursive
git submodule update --init --recursive

git config -f .gitmodules --get-regexp '^submodule\..*\.path$' |
while read -r key path; do
  name=$(echo "$key" | sed -E 's/^submodule\.(.*)\.path$/\1/')
  echo "== ${name} (${path}) =="

  if [ ! -e "$path/.git" ]; then
    echo "  SKIPPED: $path has no .git (file or dir) — init failed or path missing."
    continue
  fi

  (
    set -e
    cd "$path"

    if [ -n "$(git status --porcelain)" ]; then
      echo "  SKIPPED: uncommitted changes in $path — commit/stash first."
      exit 0
    fi

    branch=$(git config -f "$repo_root/.gitmodules" "submodule.${name}.branch" 2>/dev/null || true)
    if [ -z "$branch" ]; then
      branch=$(git remote show origin | sed -n '/HEAD branch/s/.*: //p')
    fi
    if [ -z "$branch" ]; then
      echo "  SKIPPED: could not determine tracked branch for $name."
      exit 0
    fi

    before=$(git rev-parse HEAD)
    git fetch origin "$branch"
    git checkout -B "$branch" "origin/$branch"
    after=$(git rev-parse HEAD)

    if [ "$before" != "$after" ]; then
      echo "  updated ($branch): ${before:0:12} -> ${after:0:12}"
    else
      echo "  already up to date on $branch (${after:0:12})"
    fi
  ) || echo "  FAILED to sync $name — see error above."
done

echo
echo "Done. Run 'git status' / 'git diff --submodule' in the superproject to"
echo "see which submodule pointers moved, then commit deliberately if you"
echo "want the superproject to record the update."
