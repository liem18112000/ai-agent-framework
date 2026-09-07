---
name: git-submodule-sync
description: >-
  Syncs the LUZ ops repo's git submodules (luz_kubernetes,
  luz_kubernetes_infra, luz_dockerfiles) to the latest tip of their tracked
  branch, since `git submodule update` alone leaves them pinned in detached
  HEAD at whatever commit the superproject recorded. Use when a submodule
  feels stale, before starting work inside luz_kubernetes*/luz_dockerfiles,
  after pulling/switching branches in the ops repo, or when `git submodule
  status` shows a `-` (uninitialized) or `+` (out-of-sync) prefix. Don't use
  this to commit the updated submodule pointers back into the superproject —
  review what changed first and commit that separately, deliberately.
metadata:
  category: DevOps
---

# Git Submodule Sync — LUZ Ops

The ops repo's `.gitmodules` declares 3 submodules, each a **sibling repo**
under the same Bitbucket workspace, tracking **`master`**:

```
[submodule "luz_kubernetes"]       path = luz_kubernetes       url = ../luz_kubernetes       branch = master
[submodule "luz_kubernetes_infra"] path = luz_kubernetes_infra url = ../luz_kubernetes_infra branch = master
[submodule "luz_dockerfiles"]      path = luz_dockerfiles      url = ../luz_dockerfiles      branch = master
```

Resolved URLs: `bitbucket.org/axonivy-prod/luz_kubernetes`,
`.../luz_kubernetes_infra`, `.../luz_dockerfiles` (siblings of the
superproject's own repo, `.../axonivy-prod/ai-agent-framework`).

### ⚠️ A landmine already fixed here — know this before touching `.gitmodules` again

These entries **used to read `url = ./luz_kubernetes`** (single dot, no
`branch =`). That is not sibling-repo syntax — in git's relative-submodule-URL
resolution, a leading `./` means "nested inside the current repo's own path,"
not "sibling of it" (`../` is sibling; `./` appends without stripping). With
the old `./` value, resolution produced
`https://bitbucket.org/axonivy-prod/ai-agent-framework/luz_kubernetes` — a
path that doesn't correspond to a distinct repo. Bitbucket's git smart-HTTP
endpoint doesn't error on that; it silently serves **the superproject's own
`ai-agent-framework` repo** instead. Running `git submodule sync --recursive`
followed by a naive `fetch origin <branch> && checkout -B <branch>
origin/<branch>` therefore **overwrote all 3 submodules' working trees with
the ops repo's own near-empty `master` commit**, destroying their real
content (discovered and fully recovered while building this skill — the
superproject's index still had the correct pinned SHAs, so nothing was lost,
but it was close). **Never revert `.gitmodules` back to `./name` style URLs.**
If someone adds a 4th submodule later, use `../<name>` and set `branch =`
explicitly — don't leave it to implicit remote-HEAD detection.

## The problem this skill solves

`git submodule update --init --recursive` (what a fresh clone or a normal
pull leaves you with) checks out each submodule in **detached HEAD** at the
exact SHA the superproject's commit recorded — not on any branch, and not
"latest". Two people can run the same clone command weeks apart and land on
submodule commits that are months stale relative to `master`, silently,
because nothing errors. `git submodule status` shows a leading `-` if a
submodule isn't initialized yet, or a leading `+` if the checked-out commit
doesn't match what the superproject expects (e.g. after this skill runs and
moves it forward, before you've committed the new pointer).

## Common commands

```bash
# check current state before syncing
git submodule status

# one-shot: run the bundled sync script (recommended — handles dirty-tree
# and per-submodule branch detection safely; see scripts/sync-submodules.sh)
bash .claude/skills/git-submodule-sync/scripts/sync-submodules.sh

# manual equivalent for a single submodule
cd luz_kubernetes
git fetch origin master
git checkout -B master origin/master
cd ..

# after syncing, see what moved (superproject's view)
git status
git diff --submodule

# to persist the update (record the new pinned commits in the superproject)
git add luz_kubernetes luz_kubernetes_infra luz_dockerfiles
git commit -m "Bump submodules to latest master"
```

## Common commands (first-time / re-clone)

```bash
# populate submodules after cloning the ops repo (large repos — allow
# several minutes; luz_dockerfiles in particular has large blobs and can hit
# a transient "RPC failed; curl 56 Recv failure" mid-clone — just re-run the
# same command, it resumes/retries cleanly)
git submodule update --init --recursive
```

## Safety notes

Syncing moves each submodule's working tree forward to whatever is currently
at the tip of its branch — that can pull in unreviewed changes written by
someone else since the superproject's pointer was last committed. Always run
`git status`/`git diff --submodule` after syncing and read what changed
before committing the new gitlinks into the superproject, especially before
committing that bump on `feature/ops` or `master` — a submodule bump changes
what commit CI/CD (`cloudbuild-deploy-and-validate.yaml`) actually builds
from. The bundled script refuses to touch a submodule with uncommitted
changes rather than clobbering them — if it reports a skip, resolve that
manually (commit, stash, or discard deliberately) before re-running.

## Reference Directory

- `.gitmodules` — submodule declarations (`../<name>` sibling URLs, `branch = master` pinned explicitly).
- `.claude/skills/git-submodule-sync/scripts/sync-submodules.sh` — the sync script this skill runs.
